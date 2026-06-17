#!/bin/bash
# FBM Pipeline 一键启动脚本
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
ENV_FILE="$BACKEND_DIR/.env"

read_env() {
  local key="$1"
  local fallback="$2"
  if [ -f "$ENV_FILE" ]; then
    local value
    value="$(grep -E "^${key}=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed 's/^"//; s/"$//')"
    if [ -n "$value" ]; then
      echo "$value"
      return
    fi
  fi
  echo "$fallback"
}

BACKEND_PORT="$(read_env BACKEND_PORT 8190)"
FRONTEND_PORT="$(read_env FRONTEND_PORT 3190)"
BACKEND_HOST="$(read_env BACKEND_HOST 127.0.0.1)"
FRONTEND_HOST="$(read_env FRONTEND_HOST 127.0.0.1)"

echo "📦 FBM Pipeline 启动中..."

if [ ! -f "$BACKEND_DIR/.venv/bin/activate" ]; then
  echo "❌ 未找到后端虚拟环境: $BACKEND_DIR/.venv"
  echo "   请先运行: ./scripts/setup_local.sh"
  exit 1
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "❌ 未找到前端依赖: $FRONTEND_DIR/node_modules"
  echo "   请先运行: ./scripts/setup_local.sh"
  exit 1
fi

# 启动后端
echo "🔧 启动后端 ($BACKEND_HOST:$BACKEND_PORT)..."
cd "$BACKEND_DIR"
source .venv/bin/activate
uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
BACKEND_PID=$!

# 启动前端
echo "🎨 启动前端 ($FRONTEND_HOST:$FRONTEND_PORT)..."
cd "$FRONTEND_DIR"
FRONTEND_PORT="$FRONTEND_PORT" BACKEND_PORT="$BACKEND_PORT" npx vite --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

echo ""
echo "✅ FBM Pipeline 已启动!"
echo "   前端: http://localhost:$FRONTEND_PORT"
echo "   后端: http://localhost:$BACKEND_PORT"
echo "   API文档: http://localhost:$BACKEND_PORT/docs"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 捕获退出信号
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait

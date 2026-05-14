#!/bin/bash
# FBM Pipeline 一键启动脚本
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "📦 FBM Pipeline 启动中..."

# 启动后端
echo "🔧 启动后端 (port 8190)..."
cd "$BACKEND_DIR"
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8190 &
BACKEND_PID=$!

# 启动前端
echo "🎨 启动前端 (port 3190)..."
cd "$FRONTEND_DIR"
npx vite --port 3190 &
FRONTEND_PID=$!

echo ""
echo "✅ FBM Pipeline 已启动!"
echo "   前端: http://localhost:3190"
echo "   后端: http://localhost:8190"
echo "   API文档: http://localhost:8190/docs"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 捕获退出信号
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait

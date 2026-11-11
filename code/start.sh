#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
if [[ ${1:-} == --help ]]; then
  echo '用法：./code/start.sh  （启动本地 PostgreSQL、后端 8018 和网页 5173，按 Ctrl+C 停止前后端）'
  exit 0
fi
for tool in uv npm docker; do
  command -v "$tool" >/dev/null || { echo "缺少启动依赖：$tool" >&2; exit 1; }
done
docker info >/dev/null || { echo '请先启动 Docker。' >&2; exit 1; }
[[ -f .env ]] || cp .env.example .env
if [[ ! -x code/frontend/node_modules/.bin/vite ]]; then
  npm --prefix code/frontend ci --no-audit --no-fund
fi
exec uv run --locked --python 3.12 python scripts/run_learning_space.py --api-port 8018 --frontend-port 5173

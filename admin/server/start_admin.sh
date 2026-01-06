#!/bin/bash

# 设置 PYTHONPATH 包含项目根目录
export PYTHONPATH=/Users/wanzheng/src/ai_code/ragflow:$PYTHONPATH

# 切换到脚本所在目录
cd "$(dirname "$0")"

# 运行 admin 服务
echo "Starting admin service on port 9381..."
#python admin_server.py
uv run hypercorn admin_server:app --bind 0.0.0.0:9381

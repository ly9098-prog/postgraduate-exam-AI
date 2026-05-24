#!/usr/bin/env bash
# ============================================
# 2240AI 考研助手 — 一键启动脚本 (Linux/WSL)
# 用法: ./run.sh
# ============================================
set -e

cd "$(dirname "$0")/backend"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  2240AI 考研助手 — 启动中...${NC}"
echo -e "${CYAN}========================================${NC}"

# ---- 1. Python 检测 ----
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${YELLOW}❌ 未找到 Python，请先安装 Python 3.11+${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Python: $($PYTHON --version)${NC}"

# ---- 2. 虚拟环境 ----
USE_SYSTEM=false
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}📦 创建虚拟环境...${NC}"
    if $PYTHON -m venv .venv 2>/dev/null; then
        echo -e "${GREEN}✅ 虚拟环境已创建${NC}"
    else
        echo -e "${YELLOW}⚠️  创建失败，尝试安装 python3-venv...${NC}"
        if command -v apt-get &>/dev/null; then
            sudo apt-get install -y python3-venv python3-full 2>/dev/null
            if $PYTHON -m venv .venv 2>/dev/null; then
                echo -e "${GREEN}✅ 虚拟环境已创建${NC}"
            else
                echo -e "${YELLOW}⚠️  跳过 venv，使用系统 Python${NC}"
                USE_SYSTEM=true
            fi
        else
            echo -e "${YELLOW}⚠️  跳过 venv，使用系统 Python${NC}"
            USE_SYSTEM=true
        fi
    fi
else
    echo -e "${GREEN}✅ 虚拟环境已存在${NC}"
fi

# ---- 3. 安装依赖 ----
PIP_INSTALL="pip install --quiet -r requirements.txt"

if [ "$USE_SYSTEM" = false ] && [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo -e "${YELLOW}📦 安装依赖到虚拟环境...${NC}"
else
    echo -e "${YELLOW}📦 安装依赖到系统环境...${NC}"
    PIP_INSTALL="$PIP_INSTALL --break-system-packages"
fi

pip install --quiet --upgrade pip 2>/dev/null || true
$PIP_INSTALL 2>/dev/null || {
    # 如果 venv 安装失败，降级到 system
    echo -e "${YELLOW}⚠️  venv 安装失败，降级到系统环境${NC}"
    pip install --quiet --break-system-packages -r requirements.txt
}
echo -e "${GREEN}✅ 依赖安装完成${NC}"

# ---- 4. 启动 FastAPI ----
echo ""
echo -e "${CYAN}🚀 启动服务...${NC}"
echo -e "${CYAN}   访问地址: http://127.0.0.1:8000${NC}"
echo -e "${CYAN}   API 文档: http://127.0.0.1:8000/docs${NC}"
echo -e "${CYAN}   停止服务: Ctrl+C${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

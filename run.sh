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
RUNTIME_PYTHON="$PYTHON"
if [ -x ".venv/bin/python" ]; then
    RUNTIME_PYTHON=".venv/bin/python"
    echo -e "${GREEN}✅ 虚拟环境已存在${NC}"
elif [ ! -d ".venv" ]; then
    echo -e "${YELLOW}📦 创建虚拟环境...${NC}"
    if $PYTHON -m venv .venv 2>/dev/null; then
        RUNTIME_PYTHON=".venv/bin/python"
        echo -e "${GREEN}✅ 虚拟环境已创建${NC}"
    else
        echo -e "${YELLOW}⚠️  创建失败，尝试安装 python3-venv...${NC}"
        if command -v apt-get &>/dev/null; then
            sudo apt-get install -y python3-venv python3-full 2>/dev/null
            if $PYTHON -m venv .venv 2>/dev/null; then
                RUNTIME_PYTHON=".venv/bin/python"
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
    echo -e "${YELLOW}⚠️  .venv 缺少 Python，使用系统 Python${NC}"
    USE_SYSTEM=true
fi

# ---- 3. 安装依赖 ----
PIP_BREAK_SYSTEM=""

if [ "$USE_SYSTEM" = true ]; then
    echo -e "${YELLOW}📦 安装依赖到系统环境...${NC}"
    PIP_BREAK_SYSTEM="--break-system-packages"
else
    echo -e "${YELLOW}📦 安装依赖到统一 Python 环境...${NC}"
fi

"$RUNTIME_PYTHON" -m pip install --quiet --upgrade pip 2>/dev/null || true
"$RUNTIME_PYTHON" -m pip install --quiet -r requirements.txt $PIP_BREAK_SYSTEM 2>/dev/null || {
    echo -e "${YELLOW}⚠️  venv 安装失败，降级到系统环境${NC}"
    RUNTIME_PYTHON="$PYTHON"
    PIP_BREAK_SYSTEM="--break-system-packages"
    "$RUNTIME_PYTHON" -m pip install --quiet --break-system-packages -r requirements.txt
}

if [ -f "requirements-ocr.txt" ]; then
    if "$RUNTIME_PYTHON" -c "import paddleocr" 2>/dev/null; then
        echo -e "${GREEN}✅ OCR 依赖已存在${NC}"
    else
        echo -e "${YELLOW}📦 安装 OCR 依赖（PaddleOCR，首次安装可能较慢）...${NC}"
        if "$RUNTIME_PYTHON" -m pip install --quiet -r requirements-ocr.txt $PIP_BREAK_SYSTEM; then
            if ! OCR_IMPORT_ERROR=$("$RUNTIME_PYTHON" -c "import paddleocr" 2>&1 >/dev/null); then
                if [[ "$OCR_IMPORT_ERROR" == *"libgomp.so.1"* ]] && command -v apt-get &>/dev/null; then
                    echo -e "${YELLOW}⚠️  OCR 原生运行库缺失，尝试安装 libgomp1...${NC}"
                    sudo apt-get install -y libgomp1
                    "$RUNTIME_PYTHON" -c "import paddleocr" 2>/dev/null || echo -e "${YELLOW}⚠️  OCR 运行时检查仍失败，图片 OCR 将不可用${NC}"
                else
                    echo -e "${YELLOW}⚠️  OCR 运行时检查失败，图片 OCR 将不可用${NC}"
                fi
            fi
        else
            echo -e "${YELLOW}⚠️  OCR 依赖安装失败，图片 OCR 将不可用；可稍后手动执行：$RUNTIME_PYTHON -m pip install -r requirements-ocr.txt${NC}"
        fi
    fi
fi

echo -e "${GREEN}✅ 依赖安装完成${NC}"

# ---- 4. 启动 FastAPI ----
echo ""
echo -e "${CYAN}🚀 启动服务...${NC}"
echo -e "${CYAN}   访问地址: http://127.0.0.1:8000${NC}"
echo -e "${CYAN}   API 文档: http://127.0.0.1:8000/docs${NC}"
echo -e "${CYAN}   停止服务: Ctrl+C${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

"$RUNTIME_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

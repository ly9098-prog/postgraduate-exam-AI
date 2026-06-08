#!/usr/bin/env bash
# 2240AI admin frontend local debug launcher (Linux/WSL)
# Usage: ./run-admin-linux.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMIN_DIR="$ROOT_DIR/admin-frontend"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

printf "%b\n" "${CYAN}========================================${NC}"
printf "%b\n" "${CYAN}  2240AI Admin Frontend — Local Debug${NC}"
printf "%b\n" "${CYAN}========================================${NC}"

if [ ! -d "$ADMIN_DIR" ]; then
    printf "%b\n" "${YELLOW}admin-frontend directory not found: $ADMIN_DIR${NC}"
    exit 1
fi

if ! command -v node >/dev/null 2>&1; then
    printf "%b\n" "${YELLOW}Node.js is required. Please install Node.js 20+ first.${NC}"
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    printf "%b\n" "${YELLOW}npm is required. Please install npm first.${NC}"
    exit 1
fi

cd "$ADMIN_DIR"

printf "%b\n" "${GREEN}Node: $(node --version)${NC}"
printf "%b\n" "${GREEN}npm: $(npm --version)${NC}"

if [ ! -f ".env.local" ] && [ -f ".env.example" ]; then
    cp .env.example .env.local
    printf "%b\n" "${GREEN}Created admin-frontend/.env.local from .env.example${NC}"
fi

if [ ! -d "node_modules" ]; then
    printf "%b\n" "${YELLOW}Installing admin frontend dependencies...${NC}"
    if [ -f "package-lock.json" ]; then
        npm ci
    else
        npm install
    fi
fi

printf "\n%b\n" "${CYAN}Starting admin frontend...${NC}"
printf "%b\n" "${CYAN}URL: http://127.0.0.1:3000${NC}"
printf "%b\n" "${CYAN}API: ${NEXT_PUBLIC_ADMIN_API_BASE_URL:-http://localhost:8000/api/admin/v1}${NC}"
printf "%b\n" "${CYAN}Stop: Ctrl+C${NC}"
printf "%b\n\n" "${CYAN}========================================${NC}"

export NEXT_PUBLIC_ADMIN_API_BASE_URL="${NEXT_PUBLIC_ADMIN_API_BASE_URL:-http://localhost:8000/api/admin/v1}"
exec npm run dev -- --hostname 0.0.0.0 --port 3000

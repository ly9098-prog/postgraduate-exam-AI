# Bugs History

## 2026-06-01 — PaddleOCR 本地依赖链导致误报缺失

- **现象**：本地后端调试图片 OCR 时，PaddleOCR 被报告为缺失或不可用。
- **原因**：根因不是单一 Python 包缺失，而是依赖 / 运行时链路问题：先缺少系统库 `libgomp.so.1`，恢复后又遇到 NumPy 2.x 与 `opencv-python` 4.6.x 的 ABI 不兼容。
- **处理**：通过 `run.sh` 统一使用后端虚拟环境解释器；恢复系统依赖 `libgomp1`；在 `backend/requirements-ocr.txt` 中约束 `numpy>=1.26,<2.0`，避免 OpenCV ABI 不兼容。
- **验证**：使用 `backend/.venv/bin/python` 成功导入 `numpy`、`cv2`、`paddleocr`。
- **说明**：后续若再次出现“PaddleOCR 缺失”，应优先检查系统运行库、解释器路径和 NumPy / OpenCV ABI 组合，而不是只重装 `paddleocr`。

## 2026-06-01 — P4 本地后端启动端口占用

- **现象**：P4 本地后端依赖检查通过后，启动仍失败。
- **原因**：端口 `8000` 已被既有 `uvicorn` / reloader 进程占用，导致新进程无法绑定监听端口。
- **处理**：停止已有 `uvicorn` / reloader 进程后再启动；或在启动脚本中增加端口占用检查，提前给出明确提示。
- **验证**：依赖检查已通过，失败点定位为端口绑定冲突。
- **说明**：该问题不属于依赖安装失败；排查本地启动失败时应在依赖检查后继续确认端口占用。

## 2026-06-01 — 本地调试图片 OCR 功能未启用

- **现象**：小程序本地调试上传图片时，仍提示 `图片OCR功能未启用`；响应详情在部分展示链路中显示为 `{"detail":"å¾ç OCR åè½æªå¯ç¨"}`。
- **原因**：小程序 `miniprogram/config.js` 中 `DEV=false` 时请求会走生产地址，不是本地后端；本地后端图片上传接口又会在进入 OCR 流水线前检查 `settings.OCR_ENABLED`，而 `backend/.env` 未设置 `OCR_ENABLED=true` 时会被提前拦截。乱码是中文错误详情的编码错显，原始后端错误为 `图片 OCR 功能未启用`。
- **处理**：本地调试配置切回 `DEV=true`；在 `backend/.env` 设置 `OCR_ENABLED=true`；OCR 关闭分支日志增加 `APP_ENV` 和 `OCR_ENABLED` 运行时配置输出。
- **验证**：`python3 -m py_compile backend/app/api/v1/imports.py backend/app/core/config.py backend/app/core/security.py backend/app/services/user_service.py` 通过；`node -e "require('/home/lmh/projects/postgraduate-ai/miniprogram/config.js'); console.log('config ok')"` 通过；`PYTHONPATH=/home/lmh/projects/postgraduate-ai/backend python3 -m pytest /home/lmh/projects/postgraduate-ai/backend/tests/test_services/test_dev_permissions.py -q` 通过。
- **说明**：修改 `.env` 后需要重启本地后端进程；否则运行时 `settings.OCR_ENABLED` 仍可能是旧值。

## 2026-05-31 — 开发者模式导入页 403 Permission denied

- **现象**：小程序开发者模式进入导入页时，请求 `GET /api/v1/import/batches` 返回 403，前端显示 `Permission denied`，批次列表加载失败；若完全依赖服务端权限，首页题库导入入口又会在本地调试时被隐藏。
- **原因**：本地开发者应具备与超管同等权限，但此前只有前端 `config.DEV === true` 放开了入口，后端 `require_app_permission("import:read")` 仍按真实 RBAC 绑定校验；开发模式登录生成的是 `dev_` openid 普通小程序用户，不会自动建立 `app_user_admin_bindings`。
- **处理**：保留小程序端开发模式管理员入口；后端仅在 `APP_ENV` 为 `development/local/test` 且当前用户 openid 为 `dev_` 前缀时放行应用权限；`/users/me` 对本地开发用户返回 `is_admin=true`、`role=super_admin`、`permissions=["*"]`。
- **验证**：`node -e "require('/home/lmh/projects/postgraduate-ai/miniprogram/utils/auth.js'); console.log('auth ok')"` 通过；`PYTHONPATH=/home/lmh/projects/postgraduate-ai/backend python3 -m pytest /home/lmh/projects/postgraduate-ai/backend/tests/test_services/test_dev_permissions.py -q` 通过。
- **说明**：返回 403 而不是 401 说明 JWT 有效且用户存在，失败点是当前用户未命中 `import:read` 权限。生产环境不按 `dev_` openid 放行，仍要求后台绑定和 RBAC 权限。

## 2026-05-31 — users.is_banned 缺列导致登录/用户查询失败

- **现象**：接口查询 `users` 时返回 `UndefinedColumnError: column users.is_banned does not exist`，导致按 openid 查询用户失败。
- **原因**：`User` 模型已包含封禁字段，但历史数据库表结构未完成对应迁移；开发环境 `create_all()` 不会补齐既有表缺失列。
- **处理**：在 `backend/app/core/database.py` 的开发环境 `init_db()` 中增加旧表修复逻辑，自动补齐 `is_banned`、`banned_reason`、`banned_at`、`banned_by` 和 `ix_users_is_banned`。
- **验证**：`PYTHONPATH=backend pytest backend/tests/test_api/test_admin_app_users.py backend/tests/test_services/test_admin_app_user_service.py -q` 通过；手工构造旧 SQLite `users` 表验证启动修复可补齐字段和索引。
- **生产说明**：生产 PostgreSQL 仍应执行 `alembic upgrade head`，对应迁移为 `backend/alembic/versions/g7b8c9d0e1f2_users_add_banned.py`。

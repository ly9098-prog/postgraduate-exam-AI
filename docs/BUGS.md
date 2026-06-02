开发者模式权限异常

根因：
- 小程序开发者模式在前端放开了管理员入口，`miniprogram/utils/auth.js` 中 `config.DEV === true` 会让 `auth.isAdmin()` 直接返回 `true`，因此首页显示题库导入入口，导入页 `onShow` 会继续请求 `/import/batches`。
- 后端 `/api/v1/import/batches` 仍通过 `require_app_permission("import:read")` 校验真实权限；此前开发模式登录只创建普通小程序用户并签发有效 JWT，不会自动创建小程序用户与后台管理员的绑定关系。
- 日志返回 403 而不是 401，说明 JWT 有效且用户存在；失败点是权限查询未命中 `import:read`，后端返回 `Permission denied`。

修复方向：
- 保留本地调试开发者模式的前端超管入口，确保题库导入页面可见。
- 后端仅在 `APP_ENV` 为 `development/local/test` 且用户 openid 为开发模式生成的 `dev_` 前缀时，授予小程序开发者与超管同等的应用权限。
- `/users/me` 在本地开发用户场景返回 `is_admin=true`、`role=super_admin`、`permissions=["*"]`，避免前后端权限认知不一致。

本地图片 OCR 未启用

根因：
- 小程序配置 `miniprogram/config.js` 中 `DEV=false` 时，请求会发往生产地址，而不是本地 `http://localhost:8000/api/v1`；开发者工具里看到“本地调试”不等于小程序配置已切到本地后端。
- 后端图片上传接口 `/api/v1/import/image/upload` 在进入 OCR 流水线前会先检查 `settings.OCR_ENABLED`，该配置默认值为 `False`；本地后端实际加载的 `backend/.env` 未设置 `OCR_ENABLED=true` 时，会直接返回 `图片 OCR 功能未启用`。
- 响应中的 `{"detail":"å¾ç OCR åè½æªå¯ç¨"}` 是中文错误详情在展示链路中的编码错显，原始后端错误文本是 `图片 OCR 功能未启用`。

修复方向：
- 本地调试时将小程序 `DEV` 设为 `true`，确保请求进入本地后端。
- 在本地后端实际使用的 `.env` 中设置 `OCR_ENABLED=true`，使图片上传接口不再被功能开关提前拦截。
- 在 OCR 关闭分支日志中输出 `APP_ENV` 和 `OCR_ENABLED`，后续可直接从后端日志确认运行时配置是否符合预期。

#### P4本地调试后端启动失败

日志信息：

 lmh@LAPTOP-I02S97BS:~/projects/postgraduate-ai$ ./run.sh

  2240AI 考研助手 — 启动中...

✅ Python: Python 3.12.3
✅ 虚拟环境已存在
📦 安装依赖到统一 Python 环境...
✅ OCR 依赖已存在
✅ 依赖安装完成

🚀 启动服务...
   访问地址: http://127.0.0.1:8000
   API 文档: http://127.0.0.1:8000/docs

   停止服务: Ctrl+C

INFO:     Will watch for changes in these directories: ['/home/lmh/projects/postgraduate-ai/backend']
ERROR:    [Errno 98] Address already in use



## P5OCR识别失败案例

图片原文：

32.有一个计数信号量S:

1)假如若干进程对S进行28次P操作和18次V操作后，信号量S的值为0。

2)假如若干进程对信号量S进行了15次P操作和2次V操作。请问此时有多少个进程等待在信号量S的队列中？（)

A.2

B.3

C.5

D.7



图片OCR识别内容：

32.有一个计数信号量S:

1)假如若干进程对S进行28次P操作和18次V操作后，信号量S的值为0。

S的队列中？（)

A.2

B.3

C.5

D.7

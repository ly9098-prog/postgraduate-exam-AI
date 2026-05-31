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

报错日志：
api.js:47 GET http://localhost:8000/api/v1/import/batches 403 (Forbidden)(env: Windows,mp,2.01.2510290; lib: 3.6.6)
(anonymous) @ api.js:47
request @ api.js:41
get @ api.js:90
_callee$ @ import.js? [sm]:40
s @ regeneratorRuntime.js?forceSync=true:1
(anonymous) @ regeneratorRuntime.js?forceSync=true:1
(anonymous) @ regeneratorRuntime.js?forceSync=true:1
asyncGeneratorStep @ asyncToGenerator.js?forceSync=true:1
c @ asyncToGenerator.js?forceSync=true:1
(anonymous) @ asyncToGenerator.js?forceSync=true:1
(anonymous) @ asyncToGenerator.js?forceSync=true:1
loadBatches @ import.js? [sm]:52
onShow @ import.js? [sm]:23
debug.js:75 [TRACE:NO_TRACE][API_RESPONSE] {method: "GET", url: "/import/batches", statusCode: 403}
import.js? [sm]:49 加载批次列表失败 {code: 403, message: "Permission denied"}(env: Windows,mp,2.01.2510290; lib: 3.6.6)
_callee$ @ import.js? [sm]:49
s @ regeneratorRuntime.js?forceSync=true:1
(anonymous) @ regeneratorRuntime.js?forceSync=true:1
(anonymous) @ regeneratorRuntime.js?forceSync=true:1
asyncGeneratorStep @ asyncToGenerator.js?forceSync=true:1
i @ asyncToGenerator.js?forceSync=true:1
Promise.then (async)
asyncGeneratorStep @ asyncToGenerator.js?forceSync=true:1
c @ asyncToGenerator.js?forceSync=true:1
(anonymous) @ asyncToGenerator.js?forceSync=true:1
(anonymous) @ asyncToGenerator.js?forceSync=true:1
loadBatches @ import.js? [sm]:52
onShow @ import.js? [sm]:23
api.js:47 GET http://localhost:8000/api/v1/import/batches 403 (Forbidden)(env: Windows,mp,2.01.2510290; lib: 3.6.6)
(anonymous) @ api.js:47
request @ api.js:41
get @ api.js:90
_callee$ @ import.js? [sm]:40
s @ regeneratorRuntime.js?forceSync=true:1
(anonymous) @ regeneratorRuntime.js?forceSync=true:1
(anonymous) @ regeneratorRuntime.js?forceSync=true:1
asyncGeneratorStep @ asyncToGenerator.js?forceSync=true:1
c @ asyncToGenerator.js?forceSync=true:1
(anonymous) @ asyncToGenerator.js?forceSync=true:1
(anonymous) @ asyncToGenerator.js?forceSync=true:1
loadBatches @ import.js? [sm]:52
onShow @ import.js? [sm]:23
debug.js:75 [TRACE:NO_TRACE][API_RESPONSE] {method: "GET", url: "/import/batches", statusCode: 403}
import.js? [sm]:49 加载批次列表失败 {code: 403, message: "Permission denied"}(env: Windows,mp,2.01.2510290; lib: 3.6.6)

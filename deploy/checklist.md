# 2240AI — 上线前检查清单

> 部署前逐项确认，所有项目通过后方可正式上线。

---

## 功能检查

- [ ] 微信登录完整流程（wx.login → token → 自动创建用户）
- [ ] 刷题 / 交卷 / 判分
- [ ] 错题本 / 标记掌握 / SM-2 质量评分
- [ ] 复习计划 / 今日待复习列表
- [ ] 学习统计 / Dashboard
- [ ] 题库导入（Excel / PDF）→ 审核 → 入库
- [ ] AI 错题分析 / 学习建议
- [ ] AI 降级正常（DEEPSEEK_API_KEY 为空时仍可刷题）

## 安全检查

- [ ] 所有 API 有认证保护（除 `/auth/login` 和 `/health`）
- [ ] JWT 过期（7天）后处理正常
- [ ] CORS 配置仅允许小程序域名
- [ ] 数据库使用最小权限用户
- [ ] `.env` 不在代码仓库中（已配置 `.gitignore`）
- [ ] Nginx 安全头已配置（X-Frame-Options, X-Content-Type-Options 等）
- [ ] HTTPS 强制重定向已配置

## 环境变量检查

- [ ] `APP_SECRET` 已替换为 64 位随机字符串
- [ ] `DATABASE_URL` 指向生产 PostgreSQL
- [ ] `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 已填写
- [ ] `DEEPSEEK_API_KEY` 已配置（如使用 AI 功能）
- [ ] `CORS_ORIGINS` 已限制为具体域名

## 部署检查

- [ ] 云服务器已购买（建议 2C4G 以上）
- [ ] 域名已购买并 DNS 解析到服务器 IP
- [ ] HTTPS 证书已配置（Let's Encrypt / certbot）
- [ ] Docker + Docker Compose 已安装
- [ ] 生产环境 `.env` 文件已配置
- [ ] `docker compose -f docker-compose.prod.yml up -d` 启动正常
- [ ] `alembic upgrade head` 迁移成功
- [ ] `/health` 端点返回 `{"status":"ok","env":"production"}`
- [ ] Nginx 反向代理正常工作

## 小程序端检查

- [ ] `miniprogram/config.js` 的 `BASE_URL` 改为生产域名
- [ ] `DEV` 设为 `false`
- [ ] 微信小程序管理后台已配置合法域名
- [ ] 小程序提交审核前完成全流程自测

## 性能检查

- [ ] API 首页响应 < 200ms
- [ ] 统计接口响应 < 500ms
- [ ] 数据库连接池不泄露

## 监控检查

- [ ] `/health` 端点可用
- [ ] 请求日志正常输出
- [ ] 错误日志可查看

## 备份检查

- [ ] 每日自动备份脚本已配置
- [ ] 备份保留 7 天
- [ ] 备份恢复流程已验证

---

## 上线后 24 小时关注

- [ ] 服务器 CPU / 内存 / 磁盘使用率
- [ ] API 错误率
- [ ] AI API 调用成功率
- [ ] 数据库连接数
- [ ] 小程序用户反馈

你负责 OCR 整改 P5：把 PaddleOCR-VL 客户端改成有界、可取消、可审计的生产 HTTP dependency。

### 当前缺口

- 结果下载完整读入内存后才检查大小。
- URL 只做预解析，连接时仍可能 DNS rebinding。
- 没有结果域名 allowlist/签名存储策略。
- redirect 策略不明确。
- `Retry-After` helper 没有真正读取响应头。
- polling 对错误分类不足，sleep 未严格受 remaining deadline 限制。
- 没有真正 circuit breaker/bulkhead。
- multipart MIME 固定 `image/png`。
- file URL 可能被记录，泄露签名 query。
- client 生命周期未保证由应用统一关闭。
- 远端取消接口未接入。

### 必做任务

1. 单一共享 `AsyncClient`：
   - application lifespan 创建/关闭。
   - connect/read/write/pool timeout 独立配置。
   - connection limits、keepalive、HTTP/2 按服务能力配置。
2. URL 安全：
   - API base URL 使用管理员 allowlist。
   - result URL 只允许指定对象存储域名/端口。
   - 禁止 userinfo、非 https、IP literal（除显式测试白名单）。
   - 每次 redirect 逐跳验证；默认关闭自动 redirect。
   - 防 DNS rebinding：使用可信 resolver/连接层校验，或只允许固定域名并在连接后验证 peer IP。
   - 禁止 private/loopback/link-local/multicast/metadata ranges，覆盖 IPv4/IPv6。
3. 流式下载：
   - 使用 `client.stream()`。
   - 在读取中累计 compressed bytes，超过限制立即中止。
   - 限制 decompressed bytes、行数、单行长度、JSON 深度/对象数量。
   - 拒绝压缩炸弹和无 Content-Length 的无限流。
4. retry：
   - 网络瞬断、408、429、明确 5xx 才重试。
   - 401/403/404/422 等永久错误立即失败。
   - 从真实响应头读取 Retry-After。
   - exponential backoff + full jitter。
   - 每次 request 和 sleep 都使用剩余 total deadline。
5. polling：
   - 状态枚举化，未知状态有限次数后 contract failure。
   - 支持远端 job cancellation。
   - 调用端取消时传播 CancelledError 并尽力 cancel remote job。
6. circuit breaker + bulkhead：
   - open/half-open/closed 状态。
   - 独立 submit/poll/download 指标。
   - 并发舱壁和队列上限。
7. 文件契约：
   - 根据 magic bytes 检测 MIME，禁止只信 filename。
   - 限制上传大小和像素。
8. 脱敏：
   - URL 日志去掉 query/fragment。
   - 不记录 response body；只记录 status、request id、stable error code。
9. 契约 mock server：
   - 覆盖 submit/poll/result/cancel 全状态。

### 验收测试

- private/loopback/link-local/IPv6/metadata DNS 全拒绝。
- redirect 到私网拒绝。
- DNS rebinding 场景拒绝。
- 超大 body 在超过阈值时停止读取，不占满内存。
- Retry-After 生效。
- 4xx 不重试，429/503 按策略重试。
- deadline 不被 poll sleep 超出。
- CancelledError 不被吞。
- circuit open 时快速失败并回落。
- client 在应用 shutdown 后无连接泄漏。
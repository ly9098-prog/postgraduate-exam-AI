# Stage 14: 性能优化

## 1. 阶段目标

提升系统可上线能力，优化 API 响应速度、数据库查询效率、并发处理能力和 Docker 部署体验，为正式上线做准备。

## 2. MVP 范围

### 能做

- Redis 缓存热点数据
- SQL 查询优化（N+1 问题、索引优化）
- API 分页统一化
- Docker 镜像优化（多阶段构建、减少体积）
- Uvicorn/Gunicorn 生产配置
- 慢查询日志和监控
- 数据库连接池优化

### 禁止做

- 不做微服务拆分
- 不做 Kubernetes 部署
- 不做分布式架构
- 不做跨地域多活
- 不做 CDN 动态加速（仅静态资源）

## 3. 非目标

- 不实现完整的 APM 系统
- 不做全链路追踪
- 不做自动化压测（手动即可）
- 不重构现有架构

## 4. 目录结构修改

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/core/cache.py` | Redis 缓存客户端封装 |
| `backend/docker/Dockerfile` | 生产 Dockerfile（多阶段构建） |
| `backend/docker/docker-compose.yml` | Docker Compose 生产配置 |
| `backend/docker/nginx.conf` | Nginx 反向代理配置 |
| `backend/docker/supervisord.conf` | 进程管理配置（可选） |
| `backend/scripts/benchmark.py` | 简单压测脚本 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `backend/app/core/config.py` | 新增 Redis/缓存配置项 |
| `backend/requirements.txt` | 新增 redis, gunicorn 依赖 |
| `backend/app/api/` | 统一分页参数命名 |
| `backend/app/services/` | 添加缓存装饰器/逻辑 |
| `backend/Dockerfile` | 优化多阶段构建（若有） |
| `backend/.dockerignore` | 优化忽略规则 |

## 5. 数据库变更

### 索引优化（根据实际慢查询添加）

```
-- 示例高优先级索引
CREATE INDEX idx_practice_records_user_date ON practice_records(user_id, answered_at);
CREATE INDEX idx_review_schedules_next_review ON review_schedules(user_id, next_review_at);
CREATE INDEX idx_wrong_questions_user ON wrong_questions(user_id, subject);
```

### 表结构不变

不修改现有表结构，仅新增索引。

## 6. API 变更

### 统一分页格式

所有分页 API 统一使用：

```json
{
    "items": [...],
    "total": 100,
    "page": 1,
    "page_size": 20,
    "total_pages": 5
}
```

Query 参数统一：
- `page` (int, default 1)
- `page_size` / `size` 统一为 `page_size` (int, default 20)
- `page_size` 最大 100

### 新增缓存端点

```
GET /api/v1/cache/stats       # 缓存命中统计（管理员）
DELETE /api/v1/cache/clear     # 清除缓存（管理员）
```

## 7. Service 设计

### 新增：`core/cache.py`

```python
import json
from functools import wraps
from typing import Any, Callable, Optional

from app.core.config import settings


class CacheClient:
    """Redis 缓存客户端封装。

    如果 Redis 不可用，静默降级为无缓存。
    """

    def __init__(self):
        self._client = None
        self._enabled = bool(settings.REDIS_URL)
        self._stats = {"hits": 0, "misses": 0}

    async def get(self, key: str) -> Any | None:
        """获取缓存。"""
        if not self._enabled:
            return None
        try:
            val = await self._client.get(key)
            if val:
                self._stats["hits"] += 1
                return json.loads(val)
            self._stats["misses"] += 1
            return None
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """设置缓存。"""
        if not self._enabled:
            return
        try:
            await self._client.set(key, json.dumps(value), ex=ttl)
        except Exception:
            pass

    async def delete(self, pattern: str) -> None:
        """按模式删除缓存。"""
        ...

    def get_stats(self) -> dict:
        """缓存命中统计。"""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0
        return {**self._stats, "hit_rate": hit_rate}


# 全局缓存客户端
cache = CacheClient()


def cached(ttl: int = 300, key_prefix: str = ""):
    """缓存装饰器。

    Usage:
        @cached(ttl=600, key_prefix="practice_stats")
        async def get_stats(user_id, subject):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}:{hash(str(args) + str(kwargs))}"
            result = await cache.get(cache_key)
            if result is not None:
                return result
            result = await func(*args, **kwargs)
            await cache.set(cache_key, result, ttl=ttl)
            return result
        return wrapper
    return decorator
```

### 缓存策略

| 数据 | 缓存策略 | TTL |
|------|---------|-----|
| 刷题统计 | 用户维度，按 user_id | 5 分钟 |
| 今日复习队列 | 用户维度 | 1 分钟 |
| 复习统计 | 用户维度 | 5 分钟 |
| 题目列表（不含答案） | 全量，较少变更 | 10 分钟 |
| 知识点列表 | 全量 | 1 小时 |
| 题库元信息 | 全量 | 1 小时 |

### SQL 优化清单

- [ ] N+1 查询检测：所有 `SELECT * FROM questions WHERE id IN (...)` 改为批量查询
- [ ] 懒加载预防：关系字段使用 `selectinload` 或 `joinedload`
- [ ] 分页优化：所有列表查询使用 `limit/offset` 或 cursor-based pagination
- [ ] COUNT 优化：使用 `EXPLAIN ANALYZE` 检查大表 COUNT
- [ ] 索引覆盖：高频查询字段建立复合索引
- [ ] 避免 SELECT *：仅查需要的字段

## 8. Schema 变更

无 schema 变更。统一分页响应可通过通用模型实现：

```python
class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    total_pages: int
```

## 9. 测试计划

### 新增/修改测试文件

`backend/tests/test_services/test_cache.py`

| 测试用例 | 描述 |
|---------|------|
| `test_cache_get_set` | 基本读写 |
| `test_cache_ttl` | 过期失效 |
| `test_cache_disabled` | Redis 不可用时降级 |
| `test_cache_decorator` | 装饰器生效 |
| `test_cache_stats` | 命中统计 |
| `test_redis_unavailable_graceful` | Redis 异常降级 |

### 性能测试

```bash
# 简单压测（使用 wrk 或 locust）
# API latency 目标：
#   - 缓存命中 < 50ms
#   - 缓存未命中 < 200ms
#   - 批量操作 < 500ms
```

## 10. UI 影响范围

无 UI 影响。所有优化对前端透明。

## 11. 风险与兼容性

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Redis 单点故障 | 缓存不可用 | 静默降级，不影响核心功能 |
| 缓存与 DB 不一致 | 数据短暂过期 | 短 TTL + 主动失效 |
| Docker 镜像过大 | 部署慢 | 多阶段构建 + alpine |
| 连接池耗尽 | API 拒绝服务 | 合理配置 pool_size + overflow |

## 12. 开发顺序

### Step 1: 分析瓶颈

- 检查现有 API 慢查询
- 分析数据库查询计划
- 确定缓存热点

### Step 2: Redis 缓存

- 实现 CacheClient
- 添加缓存装饰器
- 为高频接口添加缓存

### Step 3: SQL 优化

- 逐一修复 N+1 查询
- 添加缺失索引
- 优化分页

### Step 4: Docker 优化

- 多阶段构建
- 减少依赖层
- 配置 nginx 反向代理

### Step 5: 生产配置

- Uvicorn/Gunicorn worker 配置
- 连接池配置
- 日志配置

### Step 6: 测试 + 压测

## 13. 验收标准

- [ ] Redis 缓存正常工作，命中率 > 50%
- [ ] 缓存不可用时静默降级
- [ ] 所有列表 API 统一分页格式
- [ ] 无 N+1 查询问题
- [ ] Docker 镜像体积 < 500MB
- [ ] API 响应时间：缓存命中 < 50ms，未命中 < 200ms
- [ ] 压测 100 并发无错误
- [ ] 全量测试零回归

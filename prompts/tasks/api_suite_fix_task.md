## 🔧 任务：修复 PaddleOCR-VL API contract 不一致问题（P0）

------

## 一、问题说明

当前 PaddleOCR-VL 官方 API 实际返回结构为：

```json
{
  "code": 0,
  "msg": "Success",
  "data": {
    "jobId": "xxx"
  }
}
```

但当前后端 client 存在以下问题：

- ❌ 错误假设字段：`job_id`
- ❌ 未正确解析 `data.jobId`
- ❌ 将“字段不存在”误判为失败
- ❌ retry 被错误触发（3次失败实际上是成功响应）

------

## 二、必须修改内容（P0）

### 1. 修复 jobId 解析逻辑（必须改）

在 `PaddleOCRVLClient._submit_job()` 中：

#### ❌ 当前错误逻辑（示例）

```python
job_id = response["job_id"]
```

------

#### ✅ 修改为（严格对齐官方API）

```python
data = response.get("data", {})

job_id = (
    data.get("jobId")
    or data.get("job_id")
)
```

------

## 三、必须修复：成功判断逻辑（P0）

### ❌ 当前错误逻辑（禁止）

```python
if "job_id" not in response:
    raise Exception
```

------

### ✅ 改为标准 API contract 判断：

```python
if response.get("code") != 0:
    raise Exception(f"PaddleOCR-VL error: {response}")
```

------

## 四、必须修复：retry 触发条件（P0）

### ❌ 错误逻辑：

- 字段缺失 = failure ❌

------

### ✅ 正确逻辑：

只有以下情况才 retry：

- HTTP != 200
- code != 0
- request exception

------

## 五、建议新增：兼容层（防未来 API 变动）

在 client 增加统一解析函数：

```python
def _extract_job_id(resp: dict) -> str:
    data = resp.get("data", {})
    return data.get("jobId") or data.get("job_id")
```

------

## 六、必须增加日志（用于验证问题已修复）

```python
logger.info(f"[PaddleOCR-VL] raw response: {response}")
logger.info(f"[PaddleOCR-VL] extracted job_id: {job_id}")
```

------

## 七、最终验收标准

必须满足：

### ✅ API层

- jobId 能正确解析
- 不再出现 “No job_id in response”
- retry 次数下降到 0~1

------

### ✅ pipeline层

- PaddleOCR-VL 成功率 > 95%
- 不再 fallback deepseek（除真实失败）

------

### ✅ 日志验证

必须看到：

```
[PaddleOCR-VL] extracted job_id = xxx
```

------

## 八、禁止行为（非常重要）

❌ 不允许继续用 `job_id` 作为唯一字段
❌ 不允许用字段缺失判断 success
❌ 不允许 retry mask 掉成功响应
❌ 不允许吞掉 response.data

------

# 🚀 一句话总结给

> PaddleOCR-VL API 实际返回 jobId（data.jobId），当前 client 按 job_id 解析导致成功请求被误判失败。请修复 response contract 解析 + retry 条件，使 success 判定基于 code != 0，而不是字段存在性。

------


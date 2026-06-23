## 📌 任务名称：修复 batch-image 并发导入失败 + 增强 OCR 可视化日志

### 🎯 背景问题

在以下页面存在严重稳定性问题：

```
admin-frontend/src/app/(admin)/imports/batch-image
```

------

### ❌ 当前问题现象

#### Case 1：

- 并发数 = 2
- 上传 2 张图片
- 结果：仅 1 张成功

------

#### Case 2：

- 并发数 = 4
- 上传 5 张图片
- 结果：全部失败

------

#### Case 3：

- 改为单张 sequential 上传
- 每次 1 张 → ✔ 正常

------

### 🚨 初步判断问题类型

该问题**不是OCR模型问题，而是前端批处理调度问题**，可能包括：

- 并发请求竞争（race condition）
- request id 覆盖
- 上传队列未隔离
- OCR job state 被复用
- Promise.all 未做错误隔离
- abort controller 被错误触发
- batch state mutation

------

# 🧠 修复目标（必须全部满足）

## ✅ 目标1：修复并发上传稳定性

### 要求：

修改 batch-image 上传逻辑，使其满足：

- ✔ 并发上传 N 张图片不会互相影响
- ✔ 每张图片拥有独立 request context
- ✔ 任意一张失败不影响其他图片
- ✔ 支持并发 1~10 稳定运行

------

### 🔧 要求实现：

在前端增加：

```ts
concurrentUploadQueue
```

必须满足：

- 每个 task 独立 state
- 不共享 OCR response object
- 不共享 loading flag
- 不复用 mutation object

------

### 推荐修复方向：

- 改 Promise.all → Promise.allSettled
- 或改 worker queue（推荐）
- 或 semaphore 控制并发

------

# ✅ 目标2：增加 OCR 全链路可视化日志（重点）

当前问题：

> ❌ OCR 导入过程不可观测，日志太少

------

## 🔧 要求新增日志系统（前端）

在 batch-image 页面增加：

### 📌 OCR Pipeline 可视化日志

必须展示：

```
[图片1]
→ 上传成功
→ OCR开始
→ OCR识别中...
→ OCR完成（2.3s）
→ 结构解析中...
→ 题目拆分完成
→ 入库成功

[图片2]
→ 上传成功
→ OCR开始
→ ❌ OCR失败（错误原因）
```

------

## 📊 必须记录字段：

每一步必须有：

```ts
{
  imageId: string,
  step: "upload" | "ocr" | "parse" | "split" | "save" | "error",
  status: "pending" | "success" | "failed",
  duration?: number,
  message?: string,
  timestamp: number
}
```

------

## 📌 UI要求：

在 batch page 增加：

- 实时 log panel
- 每张图片独立 log stream
- 支持 collapse / expand
- error 高亮显示
- success 绿色标记
- running loading 动画

------

# ✅ 目标3：增加并发隔离 Debug 信息（关键）

每个 request 必须带：

```ts
requestId
imageId
batchId
```

------

## 必须在 network / console 可见：

```
[OCR-BATCH] requestId=xxx imageId=1 step=ocr_start
[OCR-BATCH] requestId=xxx imageId=2 step=ocr_start
```

------

# 🧪 验收标准

必须满足：

## ✔ 并发稳定性

- 2张并发 → 2张成功
- 5张并发 → ≥ 4张成功（允许单张OCR失败但不能全挂）

------

## ✔ 日志可观测性

- 每张图片都有完整 OCR 生命周期日志
- 能看到失败步骤
- 能看到耗时

------

## ✔ 失败隔离

- 单张失败不影响 batch

------

# 🚫 禁止修改

严格禁止：

- ❌ 修改 OCR 后端模型逻辑
- ❌ 修改 pipeline 核心处理逻辑
- ❌ 改变 API 返回 schema
- ❌ 改动数据库结构

------

# 🧠 本质要求总结

你只是在做三件事：

1. 修复 batch 并发隔离问题
2. 增加 OCR 可视化日志
3. 增加 request trace debug 能力

------


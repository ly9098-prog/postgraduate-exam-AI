# Claude Prompt（OCR识别路线功能开发）

你是一个资深全栈工程师，负责在现有 Admin 前端系统中新增「OCR识别路线切换功能」，用于控制题目导入时的 OCR 处理方式。

该功能属于导入任务系统的一部分，涉及前端 UI + 后端 API 调用参数扩展，但本次重点是前端改造与请求参数传递一致性设计。

------

## 一、功能目标

在以下页面中新增一个「OCR识别路线选择器」：

```
/admin-frontend/src/app/(admin)/imports/tasks/
/admin-frontend/src/app/(admin)/imports/tasks/batch-image
```

用户在执行批量导入或图片导入任务时，可以选择 OCR 处理方式：

### OCR路线（新增枚举字段）

```ts
ocr_mode: "api" | "local"
```

------

## 二、两种模式定义

### 1）API模式（api）

- 调用 `paddleocr-vl API`
- 后端直接走外部 OCR 服务
- 返回结构化识别结果（题目结构已初步解析）
- 后端将结果直接进入「审核池（review pool）」

#### 特点：

- 快
- 依赖外部服务
- 质量较高（通常）

------

### 2）本地模式（local）

- 使用本地完整 OCR pipeline
- 流程包括：
  - PaddleOCR 本地识别
  - layout analysis
  - text normalizer
  - question splitter
  - AI repair（如启用）
- 输出标准 `NormalizedQuestion[]`
- 再进入审核池

#### 特点：

- 完整控制链路
- 更稳定可调试
- 更慢

------

## 三、前端改造范围

### 1）页面位置

必须在以下两个页面增加 UI 控件：

#### （1）tasks 页面

```
/admin-frontend/src/app/(admin)/imports/tasks/
```

#### （2）batch-image 页面

```
/admin-frontend/src/app/(admin)/imports/tasks/batch-image
```

------

### 2）UI需求

新增一个「OCR处理方式」选择器：

推荐 UI：

- Radio Group 或 Select
- 默认值：`local`

```text
OCR识别方式：

( ) 本地模式（完整OCR pipeline）
( ) API模式（PaddleOCR-VL）
```

------

### 3）提交数据结构修改

在原有导入请求 payload 中新增字段：

```ts
{
  ...
  ocr_mode: "api" | "local"
}
```

必须确保：

- batch-image 上传请求携带该字段
- tasks 页面创建导入任务携带该字段

------

## 四、后端对接约定（重要）

虽然本任务重点在前端，但必须保证字段兼容：

### API contract：

```ts
ocr_mode?: "api" | "local"
```

后端行为：

| 模式  | 后端行为              |
| ----- | --------------------- |
| api   | 调用 PaddleOCR-VL API |
| local | 执行完整 OCR pipeline |

------

## 五、状态兼容规则

如果：

```ts
ocr_mode 未传
```

默认：

```ts
ocr_mode = "local"
```

------

## 六、代码修改要求

### 1）不要破坏现有流程

必须做到：

- 不影响现有导入逻辑
- 不改变默认行为
- 不影响 review pool 入库逻辑

------

### 2）只做“可插拔参数扩展”

核心原则：

> 这是一个 routing switch，而不是 pipeline 重构

------

## 七、建议实现方式

### 1）前端 state

```ts
const [ocrMode, setOcrMode] = useState<"api" | "local">("local")
```

### 2）请求注入

```ts
payload.ocr_mode = ocrMode
```

------

### 3）组件复用建议

如果 tasks 和 batch-image 都有上传逻辑：

👉 必须抽一个公共 hook：

```ts
useImportConfig()
```

包含：

- ocr_mode
- import_type
- batch settings

------

## 八、验收标准

必须满足：

### 功能

-  UI 可切换 api / local
-  请求正确携带 ocr_mode
-  默认值 local
-  两个页面一致行为

### 稳定性

-  不影响原有导入流程
-  不影响 batch-image 并发导入
-  不影响 review pool 写入

### 兼容性

-  后端未升级时仍能运行（fallback local）

------

## 九、扩展（可选优化，但不强制）

如果时间允许，可以增加：

### 1）显示说明 tooltip

- API模式：快 / 云端 / 结构更好
- 本地模式：慢 / 可控 / 可调试

------

### 2）未来扩展预留

未来可能扩展：

```ts
ocr_mode: "api" | "local" | "hybrid"
```

请在设计时避免写死 enum switch。

------

## 十、关键设计原则

你必须严格遵守：

1. 不改 pipeline，只加 routing 参数
2. 不影响默认行为（local）
3. API mode 只是替代 OCR 输入源
4. 前端只是控制开关，不参与 OCR 逻辑
5. batch-image 与 tasks 行为必须一致


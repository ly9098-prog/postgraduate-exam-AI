这个需求其实可以拆成两个独立任务让 Claude Code 实现：

## 任务1：双环境 OCR 架构

你可以直接这样描述：

# 双环境 OCR 架构改造

目标：

构建一套支持本地开发环境和服务器生产环境的 OCR 识别架构。

## 环境配置

### 本地环境（高性能）

硬件：

- CPU：i7 16核
- GPU：RTX3060 4GB

用途：

- 扫描版书籍 PDF（100~500页）
- 王道 408 等大型题库导入
- 批量图片导入
- OCR 精度优先

要求：

1. 使用 PaddleOCR 高精度模型
2. 启用 GPU 加速
3. 启用版面分析
4. 启用表格识别
5. 启用 OCR AI Correction Layer
6. 支持并发处理
7. 支持大文件长时间任务

### 服务器环境（低配置）

硬件：

- 2核2G

用途：

- 单张题目拍照
- 少量图片上传
- 小型 PDF（<30页）
- 在线实时识别

要求：

1. 使用轻量 OCR 模型
2. CPU 模式运行
3. 关闭耗时版面分析
4. 关闭大型批处理
5. 响应速度优先
6. 保证基础识别功能可用

## 技术实现

要求实现：

### 自动环境识别

支持：

ENV=local
ENV=production

根据环境自动加载不同 OCR Pipeline。

### OCR Provider 模式

设计：

BaseOCRProvider

├── HighPerformanceOCRProvider
│ ├── PaddleOCR GPU
│ ├── PP-Structure
│ ├── AI Correction
│ └── Batch Processing

└── LightweightOCRProvider
├── PaddleOCR CPU
├── Basic Layout
├── Fast Mode
└── Single File Processing

## 上传策略

本地：

允许：

- PDF
- Excel
- 图片批量上传

服务器：

允许：

- 单张图片
- 小型 PDF

超过阈值时提示：

"建议在本地导入后同步至云端"

## 目标

保证：

1. 两套环境共用业务逻辑
2. OCR 模块可插拔
3. 本地性能最大化
4. 服务器资源占用最小化
5. 代码维护成本最低

------

## 任务2：本地数据库同步云端工作流

这是你真正需要 Claude 重点设计的部分。

# 本地题库数据库同步云端方案

项目背景：

本地电脑负责大型 OCR 导入。

服务器仅负责在线访问和轻量导入。

需要实现：

本地数据库 -> 云端数据库

的增量同步机制。

## 数据库情况

本地：
SQLite

服务器：
PostgreSQL

## 核心目标

同步时：

✅ 新题目自动新增

✅ 已修改题目自动更新

✅ 分类自动同步

✅ 标签自动同步

✅ OCR结果自动同步

❌ 不允许覆盖云端已有数据

❌ 不允许删除云端数据

❌ 不允许因同步失败导致数据丢失

## 同步模式

采用：

增量同步（Incremental Sync）

而非：

全量覆盖（Full Replace）

## 数据结构要求

每张表增加：

id
uuid
created_at
updated_at
sync_version

说明：

uuid：
跨数据库唯一标识

updated_at：
判断是否需要同步

sync_version：
解决冲突

## 同步流程

步骤1

本地导出：

sqlite

↓

sync package

JSON

步骤2

生成：

sync_manifest.json

内容：

- 导出时间
- 数据量
- 版本号
- 文件校验码

步骤3

上传云端

步骤4

服务器执行：

Merge Sync

逻辑：

如果 uuid 不存在

→ INSERT

如果 uuid 存在且本地更新时间更新

→ UPDATE

如果 uuid 存在且云端更新

→ 保留云端版本并记录冲突

步骤5

生成同步报告

输出：

新增：
xxx 条

更新：
xxx 条

跳过：
xxx 条

冲突：
xxx 条

失败：
xxx 条

## Claude 实现要求

请设计：

1. SyncService
2. ExportService
3. ImportService
4. ConflictResolver
5. SyncReport

并提供：

- 架构图
- 数据表设计
- 同步算法
- 伪代码
- Python实现方案

## 最终效果

工作流：

扫描书籍 PDF

↓

本地 OCR

↓

SQLite 入库

↓

一键同步

↓

云端 PostgreSQL 自动补充数据

↓

不覆盖已有数据

↓

不丢失数据

↓

生成同步报告

------



> **不要设计成“数据库覆盖数据库”，而是设计成 Git 类似的 Merge Sync（增量合并同步）模式。**
>
> 本地 OCR 导入的数据量远大于服务器，服务器主要作为题库发布端，因此同步原则是：
>
> - 新数据自动补充
> - 已存在数据按时间戳合并
> - 永不执行 DELETE
> - 永不执行全量覆盖
> - 同步失败可回滚
> - 支持断点续传


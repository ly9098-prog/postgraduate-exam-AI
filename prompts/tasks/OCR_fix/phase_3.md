你负责 OCR 整改 P3：让 DocumentIR 成为 OCR 之后的唯一中间表示，并修复坐标、文本和缓存语义不一致。

### 当前明确缺陷

- `_prepare_ocr_image()` 在 tracker 非空时把 orig_width/orig_height 写成 0。
- transforms 生成后没有进入 blocks 和 PageIR。
- OCR boxes 不携带对应文本，`_blocks_to_document_ir()` 通过 splitlines 下标猜测 line text。
- cache hit 丢失 transforms/provenance。
- region 常被建成整页 bbox，不能表示真实 line/region。
- legacy blocks 仍是多个下游的事实源。

### 必做任务

1. 修复 TransformTracker：
   - 正确记录原图尺寸。
   - 精确记录 EXIF、crop、deskew rotate+expand、二次 crop、resize。
   - 不允许用“居中差值”猜 crop offset；预处理函数必须返回真实 crop box。
   - polygon/bbox 使用四角映射，旋转后不能只映射两个对角点。
2. 定义 Canonical OCR line output：
   - line_id、text、polygon、bbox、confidence、flags、reading_order、provenance。
   - text 与 geometry 在同一对象中，不再分离。
3. 构建 DocumentIR：
   - PageIR 写入 original size、processed size、transforms、image ref。
   - RegionIR 使用真实 layout/line grouping，不默认整页一个 region。
   - 保存 source hash、pipeline fingerprint、engine/model/preprocess fingerprints。
4. cache schema 升级：
   - 保存完整 page-level DocumentIR 或 canonical OCR page result。
   - 必含 transforms、geometry coordinate space、provenance、schema version。
   - cache hit/miss 输出必须逐字段等价。
5. 坐标统一：
   - 最终对外 geometry 全部映射回 original page coordinate space。
   - 明确像素坐标、归一化坐标和 PDF point 的转换。
6. 迁移下游：
   - reading order、structure freeze、split、match、question bbox、visual region assign、review UI 优先直接读 IR。
   - compatibility adapter 只能在边界把 IR 转为 legacy blocks，不能反向成为 SSOT。
7. 删除不可逆 OCR 层过滤：
   - 所有低置信内容保留在 IR 并带 flag。
   - 过滤由领域质量门结合位置、重复、题型、代码/数学上下文决定。
8. schema migration：
   - 旧 cache/artifact 明确拒绝或离线迁移。
   - 不允许静默兼容缺 transforms 的数据。

### 测试

- identity/crop/resize/rotation/组合变换 round-trip。
- 随机 polygon 属性测试。
- cache miss/hit DocumentIR deep-equal（忽略时间戳字段）。
- 同一页轻微亮度/DPI/压缩变化，题号和选项集合稳定。
- 被过滤的低置信英文选项、代码符号、公式样本得到保留。
- 每个 LineIR 的 text 与 bbox 对应原图中的同一行。
- IR -> legacy -> IR 的允许损失范围有明确测试。

### 验收

- DocumentIR 是 OCR Gateway 的唯一成功输出。
- 主 pipeline 不再通过独立 text + boxes 下标对齐。
- 所有 geometry 有 coordinate_space 和 transforms provenance。
- cache 命中不改变下游结果。
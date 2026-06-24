## 🎯 目标

当前 pipeline 已稳定（Fix A + Fix B + SSOT完成），但 PaddleOCR-VL 输出存在结构性损坏：

- A/B/C/D 前缀丢失
- list 化输出
- LaTeX污染

需要在不修改 classifier / SSOT 的前提下，解决 OCR 输出不稳定问题。

------

## 🧩 Step 1：引入 OCR 双源策略（关键）

建立 OCR routing：

```
PP-OCRv6 = structure primary
PaddleOCR-VL = semantic fallback
```

### 决策规则：

- 如果 PP-OCRv6 检测到 A/B/C/D → 使用 PP-OCRv6
- 否则才使用 VL

------

## 🧩 Step 2：增加 option structure repair layer（必须）

在 VL 输出后增加：

```
repair_option_structure(text)
```

功能：

- 检测 list / latex / missing prefix
- 自动恢复：
  - A.
  - B.
  - C.
  - D.

------

## 🧩 Step 3：禁止 VL 覆盖结构信息

VL 输出只能：

- 提供 content enrichment
- ❌ 不能作为结构 source of truth

------

## 🧩 Step 4：重新跑 Case3 / Case5

验证：

- options 是否恢复 A/B/C/D
- detect_options 是否 True
- extract 是否完整

------

## 🎯 最终目标

> ✔ structure source = PP-OCRv6
>  ✔ VL = enhancement layer（不能破坏结构）
>  ✔ pipeline 不再依赖 VL 输出结构完整性

------

## ⚠️ 禁止事项

- ❌ 不允许修改 classifier / SSOT
- ❌ 不允许继续调 confidence gate
- ❌ 不允许让 VL 成为 primary structure source


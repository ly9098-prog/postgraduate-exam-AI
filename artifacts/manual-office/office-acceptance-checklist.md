# Word / WPS 人工兼容性验收清单

## 验收文件

- `artifacts/libreoffice/phase3_acceptance.docx`

## 测试环境

| 项目 | 值 |
|------|-----|
| Software | |
| Version | |
| OS | |
| Tester | |
| Date | |

## 验收项

| # | 检查项 | 通过? | 备注 |
|---|--------|-------|------|
| 1 | 文档可正常打开（无修复提示） | | |
| 2 | 中文内容显示正常 | | |
| 3 | 页眉内容显示 | | |
| 4 | 页脚页码（PAGE）显示正常 | | |
| 5 | 总页数（NUMPAGES）显示正常 | | |
| 6 | 图片显示 | | |
| 7 | 原生 Word 表格（w:tbl） | | |
| 8 | 水平合并单元格（colspan） | | |
| 9 | 垂直合并单元格（rowspan） | | |
| 10 | colspan + rowspan 组合 | | |
| 11 | 内联公式（OMML）显示 | | |
| 12 | 块公式（OMML display） | | |
| 13 | 矩阵公式 | | |
| 14 | 化学公式（Unicode 下标） | | |
| 15 | 代码块（等宽字体） | | |
| 16 | 长题分页 | | |
| 17 | 分组标题 | | |
| 18 | 答案列表 | | |
| 19 | 解析内容 | | |

## 结果

- [ ] 通过 — 所有项正常工作
- [ ] 部分通过 — 见备注
- [ ] 不通过

## 备注

<!-- 记录具体异常和截图路径 -->

---

## LibreOffice 自动转换记录

```bash
soffice --headless --convert-to pdf --outdir artifacts/libreoffice artifacts/libreoffice/phase3_acceptance.docx
```

- LibreOffice 版本：当前环境未安装（CI 环境需安装 `libreoffice-writer`）
- PDF 路径：`artifacts/libreoffice/phase3_acceptance.pdf`
- DOCX 路径：`artifacts/libreoffice/phase3_acceptance.docx`

**生产环境安装命令**：
```bash
apt-get install -y libreoffice-writer fonts-wqy-zenhei fonts-wqy-microhei
```

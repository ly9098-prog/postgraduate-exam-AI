- 1. 继续深度修复“导入题目后刷题页面内容重复拼接”的问题。之前修复不完整，目前仍存在严重的数据重复问题，而且这次已经可以明确看出不是简单的 UI 渲染问题，而是“文本内容被重复拼接后入库或返回”。

     当前错误示例：

     单选题
     某文件系统采用索引分配方式，每个文件索引块可存放128个盘块地址。若文件大小为256KB，盘块大小为1KB，且采用直接索引与一级间接索引结合的方式（前10个为直接索引，第11个为一级间接索引），则访问文件最后1KB数据需要读取的索引块个数为（ ）

     某文件系统采用索引分配方式，每个文件索引块可存放128个盘块地址。若文件大小为256KB，盘块大小为1KB，且采用直接索引与一级间接索引结合的方式（前10个为直接索引，第11个为一级间接索引），则访问文件最后1KB数据需要读取的索引块个数为（ ）

     A. 1
     1

     B. 2
     2

     C. 3
     3

     D. 4
     4

     可以明显看出：

     1. 整个题干被完整重复一次
     2. 每个选项内容也被重复一次
     3. 重复模式是：
        “原文本 + 换行 + 原文本”
     4. 说明不是随机乱码，而是：
        - parser append 两次
        - normalize 执行两次
        - merge 时重复拼接
        - markdown/text 提取重复
        - OCR + 原文本双重合并
        - 或 response formatter 重复处理

     ========================
     【必须重点排查】
     ========================

     不要只修 UI，必须完整追踪数据流：

     PDF/TXT/Word
     → parser
     → normalize
     → import service
     → database
     → publish
     → practice API
     → frontend formatter
     → page render

     每一层都打印并验证数据。

     必须确认：

     - 哪一层第一次出现重复
     - 哪一层把文本拼接成：
       text + '\n' + text
     - 是否数据库里已经是重复数据
     - 是否 API 返回已经重复
     - 是否前端 formatQuestion() 再次 append

     ========================
     【重点检查这些高危逻辑】
     ========================

     1. normalizeQuestion()

     检查是否：

     question.content += normalized_content

     而不是：

     question.content = normalized_content

     2. option merge

     错误示例：

     option.text += extracted_text

     导致：

     1
     1

     3. parser line join

     错误示例：

     content = '\n'.join(lines)
     content += '\n' + '\n'.join(lines)

     4. OCR + 原文本 merge

     可能：

     final_text = raw_text + '\n' + ocr_text

     但两个内容实际上完全一样。

     5. markdown/html 转换

     检查：
     - html2text
     - markdown parser
     - rich text parser
     - latex parser

     是否重复输出。

     6. import retry

     检查：
     - 导入失败后是否重新 append
     - transaction rollback 是否重复提交
     - publish 时是否再次 normalize

     7. frontend formatter

     重点检查：

     practice.js
     question-card
     option formatter
     rich-text parser

     是否：

     displayText = text + '\n' + text

     ========================
     【增加调试日志】
     ========================

     必须打印：

     1. parser 输出
     2. normalize 前
     3. normalize 后
     4. 入库前
     5. 数据库实际值
     6. API response
     7. 小程序 setData 前
     8. 页面 render 前

     输出长度与 hash：

     len(content)
     md5(content)

     快速定位是哪一步开始重复。

     ========================
     【必须新增“重复折叠算法”】
     ========================

     新增安全文本去重函数：

     deduplicate_repeated_text()

     要求：

     仅处理：
     “完全重复的上下拼接”

     例如：

     abc
     abc

     → abc

     1
     1

     → 1

     但：

     abc
     def

     不能误删。

     支持：

     - 多行重复
     - 选项重复
     - 题干重复
     - 解析重复
     - OCR 重复

     推荐思路：

     1. trim
     2. split lines
     3. 判断前半部分是否等于后半部分
     4. 判断 normalized hash 是否一致
     5. 再安全折叠

     禁止：
     - 模糊删除
     - 正则暴力替换
     - 误伤正常内容

     ========================
     【数据库修复】
     ========================

     必须编写数据修复脚本：

     修复已经导入的重复题目。

     处理字段：

     - content
     - options
     - answer
     - explanation

     要求：

     - 幂等
     - 可重复执行
     - 输出修复数量
     - 不误伤正常题目

     ========================
     【前端修复】
     ========================

     重点检查：

     1. setData merge
     2. computedQuestion
     3. rich-text parser
     4. markdown render
     5. option component
     6. practice page 生命周期

     避免：

     旧 state + 新 state 拼接。

     ========================
     【测试要求】
     ========================

     新增：

     1. parser 测试
     2. normalize 测试
     3. deduplicate 测试
     4. API 测试
     5. 小程序 formatter 测试
     6. 回归测试

     测试样例：

     输入：

     abc
     abc

     输出：

     abc

     输入：

     1
     1

     输出：

     1

     输入：

     abc
     def

     输出保持不变。

     ========================
     【最终输出】
     ========================

     完成后输出：

     1. 根因定位
     2. 首次出现重复的位置
     3. 为什么之前修复失败
     4. 修复方案
     5. 去重算法说明
     6. 数据修复脚本说明
     7. 修改文件列表
     8. 测试结果
     9. 真机验证结果
     10. 是否影响旧数据

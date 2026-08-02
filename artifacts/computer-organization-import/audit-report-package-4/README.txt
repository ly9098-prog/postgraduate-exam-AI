question_imports 第四次审计交付说明

输入：questions(4).csv，共528条。
源依据：cs_ds.pdf 未OCR页面图像。

本轮新发现并修正6条记录、13个字段：
- 652：A/B变量X1应为x1
- 653：A变量X1应为x1
- 752：A项阶码多识别1位
- 880：M下标SP被识别为MsP/Msp，纯文本统一为M_SP
- 894：B/C/D逻辑非上划线丢失，修正版使用LaTeX形式\\overline{...}
- 1012：Intel与Core之间空格丢失

另有8条PDF源页本身疑似笔误，未自动修改。
当前CSV不包含媒体字段，无法验证此前13张截图是否已经上传或关联。

# 导入题库后题干结构被破坏

##### 导入前

```tex
下列关于线性表的存储结构的描述，正确的是()。
I.线性表的顺序存储结构优于其链式存储结构
II.链式存储结构比顺序存储结构能更方便地表示各种逻辑结构
III.若频繁使用插入和删除结点操作，则顺序存储结构更优于链式存储结构
IV.顺序存储结构和链式存储结构都可以进行顺序存取

```

##### 导入后

```tex
下列关于线性表的存储结构的描述，正确的是()。
I.线性表的顺序存储结构优于其链式存储结构II.链式存储结构比顺序存储结构能更方便地表示各种逻辑结构III.若频繁使用插入和删除结点操作，则顺序存储结构更优于链式存储结构IV.顺序存储结构和链式存储结构都可以进行顺序存取

```

##### 接口响应数据

```json
{
    "id": 138,
    "subject": "exam408-ds",
    "question_type": "single_choice",
    "content": {
        "text": "下列关于线性表的存储结构的描述，正确的是()。\nI.线性表的顺序存储结构优于其链式存储结构II.链式存储结构比顺序存储结构能更方便地表示各种逻辑结构III.若频繁使用插入和删除结点操作，则顺序存储结构更优于链式存储结构IV.顺序存储结构和链式存储结构都可以进行顺序存取"
    },
    "options": {
        "A": "I、II、III",
        "B": "II、IV",
        "C": "II、III",
        "D": "I、IV"
    },
    "answer": "B",
    "analysis": "I错误：顺序和链式各有优劣，不能绝对说谁优；II正确：链式存储通过指针能方便表示树、图等逻辑结构；III错误：频繁插入删除时链式更优；IV正确：顺序存储支持随机存取和顺序存取，链式存储只支持顺序存取。因此只有II和IV正确。",
    "knowledge_points": [
        "线性表",
        "顺序存储结构",
        "链式存储结构"
    ],
    "difficulty": 3,
    "source": "1.png",
    "source_type": "txt",
    "source_file": "1.png",
    "import_batch_id": "REVIEW_20260618_234446_c97222",
    "raw_content": "{'schema_version': 'v1', 'subject': '', 'question_type': 'single_choice', 'stem': '下列关于线性表的存储结构的描述，正确的是()。\\nI.线性表的顺序存储结构优于其链式存储结构\\nII.链式存储结构比顺序存储结构能更方便地表示各种逻辑结构\\nIII.若频繁使用插入和删除结点操作，则顺序存储结构更优于链式存储结构\\nIV.顺序存储结构和链式存储结构都可以进行顺序存取', 'options': [{'key': 'A', 'text': 'I、II、III'}, {'key': 'B', 'text': 'II、IV'}, {'key': 'C', 'text': 'II、III'}, {'key': 'D', 'text': 'I、IV'}], 'blank_option_groups': [], 'answer': 'B', 'analysis': 'I错误：顺序和链式各有优劣，不能绝对说谁优；II正确：链式存储通过指针能方便表示树、图等逻辑结构；III错误：频繁插入删除时链式更优；IV正确：顺序存储支持随机存取和顺序存取，链式存储只支持顺序存取。因此只有II和IV正确。', 'raw_text': '01.下列关于线性表的存储结构的描述，正确的是()。\\nI.线性表的顺序存储结构优于其链式存储结构\\nII.链式存储结构比顺序存储结构能更方便地表示各种逻辑结构\\nIII.若频繁使用插入和删除结点操，则顺序存储结构更优于链式存储结构\\nIV. 顺序存储结构和链式存储结构都可以进行顺序存取\\nD. I、IV\\nC. II、II\\nB. II、IV\\nA. I、II、II', 'knowledge_points': [], 'difficulty': 3, 'source': {'file': '1.png', 'page': 1, 'type': 'txt'}, 'is_valid': True, 'errors': [], 'warnings': ['missing_answer_for_objective_question'], 'stem_hash': '2b8d5783', 'confidence_score': 0.9, 'risk_flags': [], 'ai_validation': {'is_valid': True, 'issues': [], 'severity': 'none'}}",
    "image_url": null,
    "year": null,
    "review_status": "approved",
    "is_active": true,
    "created_at": "2026-06-18T16:09:18",
    "updated_at": "2026-06-18T16:09:18",
    "import_record": null
}
```

##### 问题
- 题干中列举项（I/II/III/IV 分项）之间的换行符在存储时丢失，所有文本拼成一段
- raw_content 中 \n 保留完好，但最终 content.text 中 \n 仅在首行后保留
- 问题出在 OCR 解析 → AI 标准化 → 入库的管线中，换行符被过滤

##### 修复
- 定位管线中丢失 \n 的环节
- 保留 stem 文本中的显式换行结构，尤其是列举项/多行题干格式

##### 涉及页面
- **管理端** (`admin-frontend/`) — 题目详情/题库管理页面，直接调用 API 展示 `content.text`
- **刷题页** (`miniprogram/pages/practice/`) — 用户刷题时题干文本在此渲染
- **错题本** (`miniprogram/pages/wrong-book/`) — 错题回顾时题干文本在此渲染
- **错题详情** (`miniprogram/pages/wrong-detail/`) — 错题详情页展示题干
- **刷题结果** (`miniprogram/pages/practice-result/`) — 刷题结果页展示题干

---

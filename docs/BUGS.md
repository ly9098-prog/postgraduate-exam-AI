## [P0] admin题库页批量删除报错

页面路径：admin-frontend/src/app/(admin)/questions/

```python
IntegrityError: (raised as a result of Query-invoked autoflush; consider using a session.no_autoflush block if this flush is occurring prematurely) (sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) <class 'asyncpg.exceptions.UniqueViolationError'>: duplicate key value violates unique constraint "audit_logs_pkey" DETAIL: Key (id)=(1) already exists. [SQL: INSERT INTO audit_logs (operator_id, operator_name, action, resource_type, resource_id, severity, detail, ip, user_agent, status, error_message) VALUES ($1::INTEGER, $2::VARCHAR, $3::VARCHAR, $4::VARCHAR, $5::VARCHAR, $6::VARCHAR, $7::JSON, $8::VARCHAR, $9::VARCHAR, $10::VARCHAR, $11::VARCHAR) RETURNING audit_logs.id, audit_logs.created_at] [parameters: (1, 'lmh_admin_01', 'question.delete', 'question', '55', 'critical', '{"before": {"is_active": true}, "after": {"is_active": false}}', '172.24.0.5', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36', 'success', None)] (Background on this error at: https://sqlalche.me/e/20/gkpj)
```

## [P1] admin文本导入过滤逻辑有问题

##### 问题描述

对于已在题库中删除的题目，使用文本导入功能重新导入时，系统仍提示“题库已存在该题数据”，导致导入失败，该题目被过滤掉。
以下是润色后的描述，语言更清晰、问题指向更明确：

---

## [P2]修复文本导入解析功能中题目解析内容显示不美观的问题

涉及显示页面：

```
miniprogram/pages/practice/

miniprogram/pages/practice-result/

miniprogram/pages/wrong-book/

miniprogram/pages/wrong-detail/

miniprogram/pages/review-today/

admin-frontend/src/app/(admin)/questions/
```

**问题表现**：  
使用文本导入时，解析出的题干内容格式混乱，与原始题目相比，缺少必要的换行、代码缩进及结构层次，导致可读性差。

**原始题目内容**（格式规范，含代码块）：  

> **33.** 有两个并发进程 \(P_{1}\) 和 \(P_{2}\) ，其程序代码如下：
>
> ```
> P1() {                     P2() {
>  x = 1;      // A1          x = -3;     // B1
>  y = 2;                    c = x * x;
>  z = x + y;                print c;    // B2
>  print z;    // A2
> }
> ```
>
> 可能打印出的 \(z\) 值有（ ），可能打印出的 \(c\) 值有（ ）（其中 \(x\) 为 \(P_{1}, P_{2}\) 的共享变量）。

**当前解析结果**（不美观，代码被压缩成一行，丢失换行与缩进）：  
> 有两个并发进程 P_{1} 和 P_{2} , 其程序代码如下:P1(){ P2(){ x=1; //A1 x=-3; //B1 y=2; c=x*x; z=x+y; print c; //B2 print z; //A2 }可能打印出的 z 值有 ( ), 可能打印出的 c 值有 ( ) (其中 x 为 P_{1}, P_{2} 的共享变量)。

**期望修复**：  
解析时应保留原题中的换行、代码块格式及 LaTeX 公式标记（如 \(P_{1}\)），使展示效果与原始题目一致，提升可读性。

## [P3] 小程序番茄钟及统计页面问题

1. 当小程序处于后台或锁屏状态时，番茄钟计时结束后未触发震动提醒。
2. 番茄钟进入后台后，暂停功能失效。
3. 番茄钟因中断而提前结束时，中断前已累计的时间未被计入总学习时间。
4. 刷新番茄钟统计页面后，每次重新进入番茄钟主页面时，都会重复播放“完成一个番茄钟”的动画，随后自动进入休息倒计时，但并未将新的计时时长计入总学习时间。

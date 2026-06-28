# 题目结构显示异常

#### 案例一

##### 原题

```tex
【2019 统考真题】设 n 是描述问题规模的非负整数，下列程序段的时间复杂度是( )。

x = 0;
while (n >= (x + 1) * (x + 1))
	x = x + 1;

```

##### 小程序/admin前端显示内容

```tex
【2019 统考真题】设 n 是描述问题规模的非负整数，下列程序段的时间复杂度是( )。

x = 0;
while (n >= (x + 1) * (x + 1)) x = x + 1;

```

##### 问题
- 多行代码/算法题中，换行符在渲染时丢失，所有代码被拼成一行
- 原题清晰的代码结构（循环体另起一行）在前端变为单行，可读性严重下降

##### 修复
- 后端：确保 content.text 中的 \n 在存储和传输中不被过滤
- 前端：渲染代码块时保留 whitespace: pre-wrap，代码区域应使用 <pre> 或等宽字体

---

#### 案例二

##### 原题

```tex
【2011 统考真题】设 n 是描述问题规模的非负整数，下列程序段的时间复杂度是( )。

x = 2;
while (x < n/2) 
	x = 2 * x;
```

##### admin前端显示内容

```tex
【2011 统考真题】设 n 是描述问题规模的非负整数，下列程序段的时间复杂度是( )。

x = 2;
while (x< n / 2) x = 2 * x;
```

##### 小程序显示内容

```tex
【2011 统考真题】设 n 是描述问题规模的非负整数，下列程序段的时间复杂度是( )。

x = 2;
while (x< n
/ 2) x = 2 * x;
```

##### 问题
- 与案例一相同：代码换行符丢失导致多行代码被压缩为单行
- 小程序端更严重：\n 被错误插入表达式中间（"x< n\n/ 2"），同一段文本在两个端的 \n 处理逻辑不一致

##### 修复
- 统一前后端的 \n 渲染策略：仅在代码行末尾换行，不在行中断开表达式
- 小程序端检查 rich-text 或 view 组件的 whitespace 处理方式

---

#### 案例三

##### 原题

```tex
【2012 统考真题】求整数 n (n ≥ 0) 的阶乘的算法如下，其时间复杂度是( )。

int fact(int n) {
    if (n <= 1) return 1;
    return n * fact(n − 1);
}
```

##### 小程序/admin前端显示内容

```tex
【2012 统考真题】求整数 n (n ≥ 0) 的阶乘的算法如下，其时间复杂度是( )。

int fact(int n) {
    if (n <=
1) return 1;
    return n * fact(n − 1);
}
```

##### 问题
- 代码缩进完全丢失，条件判断后的换行位置错误（"if (n <=\n1)"）
- 原题代码结构被破坏，条件判断和函数体无法区分

##### 修复
- 代码类题干存储时应保留原始缩进和换行
- 前端渲染时应使用 <pre> 标签配合等宽字体保留格式

---

#### 案例四

##### 原题（小程序）

```tex
下列程序段的时间复杂度为( )。

if (n>=0) {
    for (int i = 0; i<n; i + +)
      for (int j = 0; j<n; j + +)
      	printf("输入数据大于或等于零\n");
}else {
    for (int j = 0; j<n; j + +) 
      printf("输入数据小于零\n");
}
```

##### 小程序显示内容

```tex
下列程序段的时间复杂度为( ).
 
if (n>=0) {
for (int i=0; i<n; i++)  for (int j=0; j<n; j++)
printf("输入数据大于或等于零KaTeX parse error: Undefined control sequence: \n at position 1: \n");
}
else {
for (int j=0; j<n; j++)  printf("输入数据小于零KaTeX parse error: Undefined control sequence: \n at position 1: \n");
}
 
下列程序段的时间复杂度为( ).
 
if (n>=0) {
for (int i=0; i<n; i++)  for (int j=0; j<n; j++)
printf("输入数据大于或等于零KaTeX parse error: Undefined control sequence: \n at position 1: \n");
}
else {
for (int j=0; j<n; j++)  printf("输入数据小于零KaTeX parse error: Undefined control sequence: \n at position 1: \n");
}xxxxxxxxxx 下列程序段的时间复杂度为( )。 if (n>=0) {for (int i=0; i<n; i++)  for (int j=0; j<n; j++)printf("输入数据大于或等于零KaTeX parse error: Undefined control sequence: \n at position 1: \n");}else {for (int j=0; j<n; j++)  printf("输入数据小于零KaTeX parse error: Undefined control sequence: \n at position 1: \n");} 下列程序段的时间复杂度为( )。 if (n>=0) {for (int i=0; i<n; i++)  for (int j=0; j<n; j++)printf("输入数据大于或等于零KaTeX parse error: Undefined control sequence: \n at position 1: \n");}else {for (int j=0; j<n; j++)  printf("输入数据小于零KaTeX parse error: Undefined control sequence: \n at position 1: \n");}【2012 统考真题】求整数 n (n ≥ 0) 的阶乘的算法如下，其时间复杂度是( )。int fact(int n) {    if (n <= 1) return 1;    return n * fact(n − 1);}
```

##### 问题
- 代码缩进完全丢失，所有代码被压缩为单行
- printf 中的 \n 被 LaTeX 渲染器拦截（"KaTeX parse error"），导致页面渲染中断
- 题干内容被重复显示（出现两次相同的代码段）
- 其他题目的内容（2012 阶乘题）错误地追加到本题目末尾，存在跨题内容污染

##### 修复
- 代码块中的 \n 应转义或使用代码块/数学模式绕过 LaTeX 处理
- 查修复制/拼接逻辑，防止题目内容被重复渲染
- 检查题目边界管理，防止跨题内容泄漏

---

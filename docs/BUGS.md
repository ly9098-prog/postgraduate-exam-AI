## [P1]修复文本导入解析功能中题目解析内容显示不美观的问题（已解决）

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
> ```tex
> P1() {                     P2() {
>  x = 1;      // A1          x = -3;     // B1
>  y = 2;                     c = x * x;
>  z = x + y;                 print c;    // B2
>  print z;    // A2		   }
> }
> ```
>
> 可能打印出的 \(z\) 值有（ ），可能打印出的 \(c\) 值有（ ）（其中 \(x\) 为 \(P_{1}, P_{2}\) 的共享变量）。

**当前解析结果**：

> 有两个并发进程 P_{1} 和 P_{2} , 其程序代码如下:P1(){ P2(){ x=1; //A1 x=-3; //B1 y=2; c=x*x; z=x+y; print c; //B2 print z; //A2 }可能打印出的 z 值有 ( ), 可能打印出的 c 值有 ( ) (其中 x 为 P_{1}, P_{2} 的共享变量)。

~~~tex
有两个并发进程P₁和P₂，其程序代码如下:

```P1() { P2() {
x = 1; / / A1 x = − 3; / / B1
y = 2; c = x * x;
z = x + y; print c; / / B2
print z; / / A2 }
}
```

可能打印出的z值有()，可能打印出的c值有()(其中x为P₁, P₂的共享变量)。
~~~

**期望修复**：  
解析时应保留原题中的换行、代码块格式及 LaTeX 公式标记（如 \(P_{1}\)），使展示效果与原始题目一致，提升可读性。

##### 期望一

```tex
P1() {                     P2() {
x = 1;      // A1          x = -3;     // B1
y = 2;                    c = x * x;
z = x + y;                print c;    // B2
print z;    // A2
}
```

##### 期望二

```tex
P1() {
 x = 1;      // A1
 y = 2;
 z = x + y;
 print z;    // A2
 }

P2() {
 x = -3;     // B1
 c = x * x;
 print c;    // B2
 }
```



## [P2] 小程序答题页题干内容重复（已解决）

```tex
有两个并发进程 \(P_{1}\) 和 \(P_{2}\) ，其程序代码如下：
P1() {                     P2() {
x = 1;      // A1          x = -3;     // B1
y = 2;                     c = x * x;
z = x + y;                 print c;    // B2
print z;    // A2		   }
}
可能打印出的 \(z\) 值有（ ），可能打印出的 \(c\) 值有（ ）（其中 \(x\) 为 \(P_{1}, P_{2}\) 的共享变量）。

有两个并发进程 \(P_{1}\) 和 \(P_{2}\) ，其程序代码如下：
P1() {                     P2() {
x = 1;      // A1          x = -3;     // B1
y = 2;                     c = x * x;
z = x + y;                 print c;    // B2
print z;    // A2		   }
}
可能打印出的 \(z\) 值有（ ），可能打印出的 \(c\) 值有（ ）（其中 \(x\) 为 \(P_{1}, P_{2}\) 的共享变量）。
```

## [P3] 题干选项解析异常（已解决）

##### 文本导入输入内容

```tex
7. 下列算法的时间复杂度为（ ）。

void fun(int n) {
    int i=0;
    while(i*i*i<=n)
    i++;
}

A. \( O(n) \)  
B. \( O(n \log_2 n) \)  
C. \( O(\sqrt[3]{n}) \)  
D. \( O(\sqrt{n}) \)  
答案：C
```

##### 原文内容

~~~tex
**7. 下列算法的时间复杂度为（ ）。**

```c
void fun(int n) {
    int i = 0;
    while (i * i * i <= n)
        i++;
}
```

A. O(n)
B. O(n log₂n)
C. O(∛n)
D. O(√n)

答案：C


~~~

## [P4] 题干选项格式异常（已解决）

##### 前端显示内容

选项和答案格式没问题此处不展示

```c
下列程序段的时间复杂度为( )。

if (n>=0) {
    for (int i = 0; i<n; i + +)        for (int j = 0; j<n; j + +)            printf("输入数据大于或等于零\n");
}
else {
    for (int j = 0; j<n; j + +)        printf("输入数据小于零\n");
}
```

##### 原文内容

```c
下列程序段的时间复杂度为( )。

if (n>=0) {
    for (int i = 0; i<n; i + +)
    for (int j = 0; j<n; j + +) 
    printf("输入数据大于或等于零\n");
}
else {
    for (int j = 0; j<n; j + +)
    printf("输入数据小于零\n");
}
```


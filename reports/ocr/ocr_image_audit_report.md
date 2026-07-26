# OCR 图片审计报告

生成时间：2026-07-17T01:54:25.832413

---

## 1. 总体统计

| 指标 | 数值 |
| --- | --- |
| 题目总数 | 513 |
| 明确带图片的题目 | 25 |
| 存在问题的题目 | 6 |
| 需人工复核题目 | 89 |
| 磁盘图片文件数 | 127 |
| 被引用的图片文件 | 25 |
| 孤立图片文件 | 102 |
| 孤立非快照图片 | 80 |

**按严重程度分类：**

| 严重程度 | 数量 |
| --- | --- |
| 高 | 3 |
| 中 | 3 |
| 低 | 0 |

**按问题类型分类：**

| 问题类型 | 数量 |
| --- | --- |
| hint_but_no_image | 3 |
| image_file_issue | 2 |
| text_only_segments | 1 |

## 2. 数据结构与图片存储

### 2.1 数据结构

| 表/字段 | 说明 |
| --- | --- |
| `questions` | 已发布题目表，共 511 条 |
| `questions.id` | 题目唯一标识 |
| `questions.content` | JSON 对象，含 text、render_mode、segments（可选）|
| `questions.image_url` | JSON 数组，每道题可关联多张图片（绝对 URL 或 /static/ 相对路径）|
| `questions.options` | JSON 对象，{A: text, B: text, ...} |
| `question_imports` | OCR 导入原始表，513 条 |
| `question_imports.parsed_content` | OCR 解析内容，含 segments（type=image 表示图片片段）|
| `question_imports.parsed_options` | OCR 选项解析 |

### 2.2 图片存储

| 项目 | 值 |
| --- | --- |
| 存储根目录 | `backend/static/question-assets/202607/` |
| 子目录 | `ds_sc/`（已迁移的正式图片） |
| 命名规则 | `q_{import_id}_p{page}_visual-v2.1.png`（内容图）|
| 快照命名 | `snapshot_q{import_id}_p{page}_visual-v2.1.png`（管理员用）|
| 哈夫曼树选项组 | `q_229_p229_option_group.png`（特殊）|
| 旧版本（canary） | `visual-v2.1_ds_{hash}_content.png` / `...snapshot.png` |
| 旧版 hash 图片 | `q_{import_id}_p{page}_{hash}.png`（visual-v2 遗留）|

## 3. 确认存在的问题

| 题目 ID | 题号 | 问题类型 | 题干摘要 | 图片路径 | 判定依据 | 严重程度 |
| --- | --- | --- | --- | --- | --- | --- |
| 147 | 200 | hint_but_no_image | 【2009统考真题】给定二叉树如右图所示。设N代表二叉树的根，L代表根结点的左子树，R 代表根结点的右子树。若遍历后的结 | N/A | text suggests image needed (右图) but no image found | high |
| 152 | 205 | hint_but_no_image | 【2014统考真题】若对右图所示的二叉树进行中序线索化，则结点X的左、右线索指向的结点 分别是（ ）。 a | N/A | text suggests image needed (右图) but no image found | high |
| 154 | 207 | hint_but_no_image | 【2017 统考真题】某二叉树的树形如右图所示，其后序序列为 e,a,c,b,d,g,f,树中与结点 a 同层的 结点是 | N/A | text suggests image needed (右图) but no image found | high |
| 294 | 369 | image_file_issue | 【2009统考真题】下列二叉排序树中，满足平衡二叉树定义的是（ ）。 | http://localhost:8000/static/question-assets/202607/visual-v | 1/1 images have issues | medium |
| 296 | 371 | text_only_segments | 【2011 统考真题】对下列关键字序列，不可能构成某二叉排序树中一条查找路径的是（ ）。 | N/A | render_mode=segments contains only text segments, no image — may indicate lost i | medium |
| 305 | 380 | image_file_issue | 下图所示是一棵（ ）。 | http://localhost:8000/static/question-assets/202607/visual-v | 1/1 images have issues | medium |

## 4. 需人工复核的题目

以下题目虽然未确认缺图，但内容类型很可能依赖图片，建议人工确认：

| 题目 ID | 题号 | 题型 | 题干摘要 | 可疑线索 |
| --- | --- | --- | --- | --- |
| 100 | 152 | single_choice | 下列关于二叉树的说法中，正确的是（ ）。 | topic hint: 下列关于二叉树的说法中，正确的是 |
| 118 | 171 | single_choice | 【2011统考真题】若一棵完全二叉树有 768个结点，则该二叉树中叶结点的个数是（ ）。 | topic hint: 该二叉树中叶结点的个数是 |
| 120 | 173 | single_choice | 【2020 统考真题】对于任意一棵高度为5且有10个结点的二叉树，若采用顺序存储结构保存, 每个结点占 1 个存储单元( | topic hint: 该二叉树需要的存储单元数量至少是 |
| 121 | 174 | single_choice | 在下列关于二叉树遍历的说法中，正确的是（ ）。 | topic hint: 下列关于二叉树遍历的说法中，正确的是 |
| 129 | 182 | single_choice | 一棵非空的二叉树的先序遍历序列与后序遍历序列正好相反，则该二叉树一定满足（ ）。 | topic hint: 该二叉树一定满足 |
| 130 | 183 | single_choice | 设结点 X 和 Y 是二叉树中任意的两个结点。在该二叉树的先序遍历序列中 X 在 Y 之前，而在其后序遍历序列中 X 在 | topic hint: 该二叉树的先序遍历序列中 X 在 Y 之前，而在其后序遍历序列中 X 在 Y 之后，则 X 和  |
| 133 | 186 | single_choice | 下列序列中，不能唯一地确定一棵二叉树的是（ ）。 | topic hint: 下列序列中，不能唯一地确定一棵二叉树的是 |
| 146 | 199 | single_choice | 某二叉树的先序序列和后序序列正好相反，则该二叉树一定是（ ）。 | topic hint: 该二叉树一定是 |
| 158 | 214 | single_choice | 森林 T=(T₁,T₂,…,Tₘ) 转化为二叉树 BT 的过程为：若 m=0，则 BT 为空；若 m≠0，则（ ）。 | topic hint: 森林 T=(T₁,T₂,…,Tₘ) 转化为二叉树 |
| 161 | 219 | single_choice | 在森林的二叉树表示中，结点M和结点N是同一父结点的左儿子和右儿子，则在该森 林中（ ）。 | topic hint: 森林的二叉树 |
| 162 | 220 | single_choice | 下列关于树和森林的说法中，正确的是（ ）。
I. 森林中的每棵树都可以转换为二叉树
II. 森林转换成二叉树后，二叉树的 | topic hint: 森林中的每棵树都可以转换为二叉树 |
| 165 | 228 | single_choice | 在有 n个叶子结点的哈夫曼树中，非叶子结点的总数是() | topic hint: 哈夫曼树 |
| 168 | 232 | single_choice | 一棵哈夫曼树共有 215个结点，对其进行哈夫曼编码，共能得到（ ）个不同的码字。 | topic hint: 哈夫曼树 |
| 169 | 233 | single_choice | 以下对于哈夫曼树的说法中，错误的是（ ） | topic hint: 哈夫曼树 |
| 170 | 234 | single_choice | 若度为 m 的哈夫曼树中，叶子结点个数为 n，则非叶子结点的个数为() | topic hint: 哈夫曼树 |
| 173 | 238 | single_choice | 【2010 统考真题】n(n≥
2)个权值均不相同的字符构成哈夫曼树，关于该树的叙述中，错误的是 （ ）。 | topic hint: 哈夫曼树 |
| 174 | 240 | single_choice | 【2015统考真题】下列选项给出的是从根分别到达两个叶结点路径上的权值序列，属于同一棵 哈夫曼树的是（ ）。 | topic hint: 哈夫曼树 |
| 189 | 261 | single_choice | 【2011统考真题】下列关于图的叙述中，正确的是（ ）。
I. 回路是简单路径
II. 存储稀疏图，用邻接矩阵比邻接表更 | topic hint: 拓扑序列 |
| 190 | 262 | single_choice | 【2013统考真题】设图的邻接矩阵 A 如下所示，各顶点的度依次是（ ）。
A=[[0,1,0,1],[0,0,1,1] | topic hint: 邻接矩阵 A 如下所示，各顶点的度依次是 |
| 196 | 268 | single_choice | 带权有向图 G 用邻接矩阵存储，则v;的入度等于邻接矩阵中（ ）。 | topic hint: 邻接矩阵存储 |
| 197 | 269 | multi_blank_choice | 一个有 n 个顶点的图用邻接矩阵 A 表示，若图为有向图，顶点 vᵢ 的入度是（ ）；若图为无向图，顶点 vᵢ 的度是（ | topic hint: 邻接矩阵 A 表示，若图为有向图，顶点 vᵢ 的入度是（ ）；若图为无向图，顶点 vᵢ 的度是 |
| 198 | 270 | single_choice | 下列哪种图的邻接矩阵是对称矩阵？ | topic hint: 邻接矩阵是 |
| 199 | 271 | multi_blank_choice | 从邻接矩阵 A=[[0,1,0],[1,0,1],[0,1,0]] 可以看出，该图共有（①）个顶点；若是有向图，则该图共 | topic hint: 邻接矩阵 A=[[0,1,0],[1,0,1],[0,1,0]] 可以看出，该图共有（①）个顶点 |
| 201 | 273 | single_choice | 用邻接表法存储图所用的空间大小(（ ）。 | topic hint: 邻接表法存储 |
| 203 | 275 | single_choice | 在有向图的邻接表存储结构中，顶点在边表中出现的次数是（ ）。 | topic hint: 邻接表存储结构中，顶点在边表中出现的次数是 |
| 205 | 277 | single_choice | 假设有 n 个顶点、é条边的有向图用邻接表表示，则删除与某个顶点v相关的所有边的 时间复杂度为（ ）。 | topic hint: 邻接表表示 |
| 206 | 278 | single_choice | 对邻接表的叙述中，（ ）是正确的。 | topic hint: 邻接表的叙述中，（ ）是 |
| 210 | 282 | single_choice | 对于一个非连通无向图G,采用深度优先遍历访问所有顶点，在 DFSTraverse 函数(见考点讲 解 DFS 部分)中调 | topic hint: DFS |
| 211 | 283 | multi_blank_choice | 对一个有 n 个顶点、e 条边的图采用邻接表表示时，进行 DFS 遍历的时间复杂度为（ ），空间复杂度为（ ）；进行 B | topic hint: DFS, 邻接表表示 |
| 212 | 284 | multi_blank_choice | 对有 n 个顶点、e 条边的图采用邻接矩阵表示时，进行 DFS 遍历的时间复杂度为（ ），进行 BFS 遍历的时间复杂度 | topic hint: DFS, 邻接矩阵表示 |
| 215 | 287 | multi_blank_choice | 用邻接表存储的图的深度优先遍历算法类似于树的（ ），而其广度优先遍历算法类似于树的 （ ）。 | topic hint: 邻接表存储 |
| 218 | 290 | single_choice | 判断有向图中是否存在回路，除可以利用拓扑排序外，还可以利用（ ）。 | topic hint: 拓扑排序 |
| 219 | 291 | single_choice | 使用 DFS 算法递归地遍历一个无环有向图，并在退出递归时输出相应顶点，这样得到的 顶点序列是（ ）。 | topic hint: DFS |
| 222 | 294 | single_choice | 对有n个顶点、é条边且使用邻接表存储的有向图进行广度优先遍历，其算法的时间复杂度是 （ ）。 | topic hint: 邻接表存储的有向图进行广度优先遍历，其算法的时间复杂度是 |
| 224 | 296 | single_choice | 【 2015统考真题】设有向图G=(V,E),顶点集V={Vo,V,V2,V3}，边集 E={vo,>，<vo,V>，< | topic hint: 深度优先遍历，则可能得到的 不同遍历序列 |
| 226 | 298 | single_choice | 任何一个无向连通图的最小生成树（ ）。 | topic hint: 最小生成树 |
| 227 | 299 | single_choice | 用Prim 算法和Kruskal算法构造图的最小生成树，所得到的最小生成树（ ）。 | topic hint: Prim 算法和Kruskal算法构造图的最小生成树，所得到的最小生成树, 最小生成树 |
| 230 | 303 | single_choice | 下面的( )方法可以判断出一个有向图是否有环(回路)。 
III.求最短路径 
IV.求关键路径 
I.深度优先遍历 Ⅱ | topic hint: 拓扑排序 |
| 232 | 306 | single_choice | 若一个有向图的顶点不能排成一个拓扑序列，则判定该有向图(（ ）。 | topic hint: 拓扑序列 |
| 234 | 308 | single_choice | 若一个有向图具有有序的拓扑排序序列，则它的邻接矩阵必定为（ ）。 | topic hint: 拓扑排序 |
| 235 | 309 | single_choice | 下列关于图的说法中，正确的是（ ）。
I. 有向图中顶点 V 的度等于其邻接矩阵中第 V 行中 1 的个数
II. 无向 | topic hint: 最小生成树, 拓扑序列, 邻接矩阵一定是对称矩阵，有向图的邻接矩阵一定是 |
| 238 | 312 | single_choice | 下列关于关键路径的说法中，正确的是（ ）。 
I.改变网上某一关键路径上的任一关键活动后，必将产生不同的关键路径 
II | topic hint: 关键路径上活动的时间延长多少，整个工程的时间 |
| 239 | 313 | single_choice | 用DFS遍历一个无环有向图，并在DFS 算法退栈返回时打印相应的顶点，则输出的顶点序列是 （ ）。 | topic hint: DFS |
| 241 | 315 | single_choice | 下列关于拓扑排序的说法中，正确的是（ ）。
I. 拓扑排序可以判断有向图中是否存在回路
II. 拓扑排序序列一定唯一
I | topic hint: 拓扑排序 |
| 243 | 317 | single_choice | 【2013统考真题】下列AOE网表示一项包含8个活动的工程。通过同时加快若干活动的 进度可以缩短整个工程的工期。下列选项 | topic hint: AOE网 |
| 244 | 318 | single_choice | 【2012统考真题】若用邻接矩阵存储有向图，矩阵中主对角线以下的元素均为零，则关于该图 拓扑序列的结论是（ ）。 | topic hint: 拓扑序列, 邻接矩阵存储有向图，矩阵中主对角线以下的元素均为零，则关于该图 拓扑序列的结论是 |
| 248 | 322 | single_choice | 【2016 统考真题】若对n个顶点、é条弧的有向图采用邻接表存储，则拓扑排序算法的时间复 杂度是（ ）。 | topic hint: 拓扑排序, 邻接表存储，则拓扑排序算法的时间复 杂度是 |
| 249 | 323 | single_choice | 【2018统考真题】下列选项中，不是如下有向图的拓扑序列的是（ ）。 | topic hint: 拓扑序列 |
| 252 | 327 | single_choice | 【2020统考真题】修改递归方式实现的图的深度优先搜索（DFS）算法，将输出（访问）顶点信息的语句移到退出递归前（即执行 | topic hint: DFS |
| 253 | 328 | single_choice | 【2020 统考真题】若使用 AOE 网估算工程进度，则下列叙述中正确的是（ ）。 | topic hint: AOE 网 |

*共 89 条记录，仅显示前 50 条*


## 5. 孤立或异常图片

### 5.1 孤立内容图片（80 个）

| 文件 | 大小 | 宽×高 | PNG 有效 | 可能原因 |
| --- | --- | --- | --- | --- |
| q_229_p108_50bb26183f33.png | 435699 | 1448×552 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_369_p286_3b118e4fa031.png | 99711 | 410×501 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_371_p288_73dac60e2a2a.png | 175561 | 525×650 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_378_p295_c7e3872cdf14.png | 232088 | 1433×562 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_380_p297_745c3f13aca4.png | 114043 | 418×553 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_388_p307_0a0da031849d.png | 121752 | 748×438 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_395_p314_5b960420d5f1.png | 147635 | 717×505 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_397_p316_f5c05507ed2f.png | 194758 | 883×470 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_400_p319_b268c5e4c682.png | 136338 | 543×545 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_402_p321_435975c196c7.png | 95113 | 629×368 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_405_p324_bdc51110ea1d.png | 120602 | 768×440 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_407_p326_73e8570b2a44.png | 234226 | 803×658 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_411_p330_13bd1d2b9620.png | 202340 | 617×642 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_412_p331_536e128c3456.png | 159894 | 823×480 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_451_p370_2791af36be30.png | 188533 | 669×650 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_457_p376_c0ab157e96e2.png | 106828 | 477×573 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_460_p379_8bdb55b12cef.png | 106230 | 451×545 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_461_p380_ad4f13dcb1ff.png | 79868 | 803×400 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_472_p391_1170e42df1d6.png | 212058 | 1005×605 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| q_480_p399_90bf6b232546.png | 163700 | 1165×298 | 是 | 旧版 hash 命名的 v2 图片，已被 v2.1 替换 |
| visual-v2.1_ds_02c788274d2f_snapshot.png | 150302 | 801×892 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_04f2521a989d_snapshot.png | 88269 | 995×1103 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_077697c3dedb_content.png | 62117 | 973×115 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_077ace09bc2f_snapshot.png | 67622 | 874×829 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_09e71f4b7caa_content.png | 32650 | 524×97 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_0c14dff1b4ed_snapshot.png | 18653 | 967×737 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_122213745759_content.png | 18321 | 765×154 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_13e2f46d469c_content.png | 22073 | 520×129 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_16f5c297e00f_snapshot.png | 158482 | 956×971 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_1ea1f363c25a_content.png | 131449 | 1594×192 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_2254c5e3e370_content.png | 57915 | 633×153 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_273e91ef2643_content.png | 98105 | 678×651 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_2dad0040dc45_content.png | 76666 | 796×154 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_2e1a24bb871a_content.png | 12016 | 704×100 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_370ebefc3a9f_snapshot.png | 80988 | 722×755 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_389b2d6f12e6_content.png | 11413 | 857×245 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_3db270440db4_content.png | 41428 | 704×140 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_42381e27e66d_content.png | 59120 | 824×423 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_45640a94d78a_snapshot.png | 17595 | 538×768 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_46220ae5a73b_content.png | 31583 | 1106×585 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_4ae1c2cb1f61_snapshot.png | 63923 | 814×813 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_5471f42048bc_content.png | 77795 | 885×651 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_5736d6c31636_content.png | 104673 | 736×634 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_5a27d05dde45_content.png | 76465 | 884×151 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_5c32aa0eb7be_snapshot.png | 118522 | 788×1103 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_5e70a88a2809_snapshot.png | 63262 | 784×813 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_6ccc7a36f0b1_snapshot.png | 167938 | 1609×1045 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_6d4cf0a12378_content.png | 108572 | 846×114 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_6ec2da9b32a4_snapshot.png | 66955 | 508×768 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_72005108326b_snapshot.png | 130847 | 899×927 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_7b7161325883_content.png | 112464 | 789×475 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_85baa098f395_snapshot.png | 121711 | 846×1086 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_86bb48841f25_content.png | 57903 | 396×276 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_8b255e84f1e8_content.png | 10998 | 741×149 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_8bd4004349f6_snapshot.png | 77727 | 710×971 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_9e274eb159ad_snapshot.png | 68456 | 934×875 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_a059986cc955_content.png | 19615 | 397×142 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_a38f3603ea15_snapshot.png | 208557 | 1704×1059 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_afd442aa1086_snapshot.png | 95704 | 1083×1002 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_b11302f40bb8_snapshot.png | 37941 | 1216×1037 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_b8fd238583b4_snapshot.png | 55218 | 814×845 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_bb409b6ab68d_snapshot.png | 270179 | 994×933 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_c02ae33c82b0_snapshot.png | 46612 | 875×875 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_c25945e2d8fb_snapshot.png | 28126 | 814×829 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_c648ed1ae227_content.png | 8354 | 428×276 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_cc6a8febdb5d_snapshot.png | 58147 | 829×835 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_ce9440f2dce3_snapshot.png | 127579 | 1016×919 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_cf0ed05b5657_snapshot.png | 182020 | 906×844 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_dad184ab2608_content.png | 63466 | 600×519 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_ebcaf69000b5_snapshot.png | 155447 | 1180×859 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_f0a757175508_content.png | 116297 | 906×467 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_f0b078055d98_snapshot.png | 29291 | 554×783 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2.1_ds_fc21e3d2e3a5_content.png | 21026 | 704×149 | 是 | canary/backfill 遗留，未被最终迁移使用 |
| visual-v2_ds_204b50c7cf55_content.png | 72464 | 579×622 | 是 | visual-v2 版本（未升级到 v2.1） |
| visual-v2_ds_39d39a3ff48f_snapshot.png | 93296 | 689×1086 | 是 | visual-v2 版本（未升级到 v2.1） |
| visual-v2_ds_4f6610a01f58_content.png | 26074 | 451×129 | 是 | visual-v2 版本（未升级到 v2.1） |
| visual-v2_ds_b7e29e8d0d3d_content.png | 46515 | 579×137 | 是 | visual-v2 版本（未升级到 v2.1） |
| visual-v2_ds_d0af00d303b0_content.png | 73617 | 579×634 | 是 | visual-v2 版本（未升级到 v2.1） |
| visual-v2_ds_d9d2ef35609c_snapshot.png | 66461 | 561×753 | 是 | visual-v2 版本（未升级到 v2.1） |
| visual-v2_ds_ff998e1faf90_snapshot.png | 93296 | 689×1086 | 是 | visual-v2 版本（未升级到 v2.1） |

### 5.2 孤立快照图片（22 个）

| 文件 | 大小 | 宽×高 |
| --- | --- | --- |
| snapshot_q229_p108_visual-v2.1.png | 464432 | 1527×544 |
| snapshot_q302_p201_visual-v2.1.png | 212631 | 1550×567 |
| snapshot_q369_p286_visual-v2.1.png | 111278 | 1527×432 |
| snapshot_q371_p288_visual-v2.1.png | 267994 | 1527×566 |
| snapshot_q378_p295_visual-v2.1.png | 136930 | 1527×494 |
| snapshot_q380_p297_visual-v2.1.png | 122532 | 1527×474 |
| snapshot_q388_p307_visual-v2.1.png | 90323 | 1527×374 |
| snapshot_q395_p314_visual-v2.1.png | 109365 | 1527×422 |
| snapshot_q397_p316_visual-v2.1.png | 254810 | 1527×490 |
| snapshot_q400_p319_visual-v2.1.png | 139929 | 1527×464 |
| snapshot_q402_p321_visual-v2.1.png | 155933 | 1527×394 |
| snapshot_q405_p324_visual-v2.1.png | 166370 | 1527×460 |
| snapshot_q407_p326_visual-v2.1.png | 406511 | 1611×688 |
| snapshot_q411_p330_visual-v2.1.png | 252739 | 1527×582 |
| snapshot_q412_p331_visual-v2.1.png | 119378 | 1527×414 |

*快照图片可能通过 `source_snapshot_url` 引用（未在 `segments` 中索引），列为孤立的快照共 22 张*


## 6. 修复建议

### 优先级 1 — 立即修复：

1. **Q.147(s200)、Q.152(s205)、Q.154(s207) 缺少二叉树图示**：这三道题明确引用"右图"（"给定二叉树**如右图所示**"），但完全没有关联图片。
   建议从原始 PDF 第 200、205、207 页裁剪对应的二叉树图，或从统考真题原卷获取。修复方式为添加 `segments` 图片段和 `image_url`。

2. **localhost URL → 替换为正式路径**：Q.294(s369)、Q.305(s380) 使用 `http://localhost:8000/static/...` 路径，生产环境不可用。
   建议改为 `/static/question-assets/202607/...` 相对路径。

3. **Q.296 render_mode=segments 但无图片**：该题 content 设置了 `render_mode: segments` 但 segments 中仅有 text，
   需确认是确实是纯文字题目还是漏了图片。

### 优先级 2 — 清理：

1. **旧版 hash 图片**（如 `q_229_p108_50bb26183f33.png`）已在 ds_sc/ 中有 v2.1 版本，
   可在确认引用完全移除后删除。

2. **canary 图片**（`visual-v2.1_ds_*` 和 `visual-v2_ds_*`）未被任何已发布题目引用，
   但可能是回退时需要的历史版本，建议迁移至存档目录。

### 优先级 3 — 增强：

1. **选项组图片的显式关联**：Q.148(s201)、Q.277(s352)、Q.293(s368)、Q.294(s369) 的 parsed_options 因选项为图片而内容为空，
   前端已通过 option_group 处理，但 image_url 字段已正确关联。

2. **source_snapshot_url 索引**：当前 22 张快照图片未在 `image_url` 字段记录（因为仅后台使用），
   建议确认快照路径在学生端不可访问。

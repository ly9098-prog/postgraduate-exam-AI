# 环境同步说明：公式函数图像到预发布/生产

## 本次操作环境

- **数据库**: `sqlite+aiosqlite:///./postgraduate.db`（本地 SQLite 开发库）
- **存储**: `backend/static/formulas/graphs/`（本地文件系统）
- **确认内容**: 35 张函数图像全部就绪（25 generated + 10 template）
- **预览地址**: `http://localhost:8000/static/formulas/...`

## 安全原则

1. 不要通过复制整个 SQLite 文件覆盖生产数据库（自增 ID 不对应）
2. 已有人工上传图像不得覆盖
3. 导入前必须 dry-run
4. 导入后重新验证线上 URL

## 同步步骤

### 1. 导出 GraphSpec 和 Asset 元数据

```bash
cd backend
source .venv/bin/activate

# 导出所有 function_graph 卡的 GraphSpec 和 Asset 记录
python -c "
import asyncio, json
from app.core.database import async_session
from app.models.formula import FormulaCard, FormulaGraphAsset
from sqlalchemy import select

async def export():
    async with async_session() as session:
        cards_r = await session.execute(
            select(FormulaCard).where(
                FormulaCard.card_type == 'function_graph',
                FormulaCard.deleted_at.is_(None),
            ).order_by(FormulaCard.id)
        )
        cards = list(cards_r.scalars().all())
        
        result = []
        for c in cards:
            assets_r = await session.execute(
                select(FormulaGraphAsset).where(
                    FormulaGraphAsset.formula_card_id == c.id
                )
            )
            assets = [{'id': a.id, 'source_type': a.source_type, 'checksum': a.checksum,
                       'image_url': a.image_url, 'thumbnail_url': a.thumbnail_url}
                      for a in assets_r.scalars().all()]
            
            result.append({
                'id': c.id,
                'title': c.title,
                'card_type': c.card_type,
                'graph_spec': c.graph_spec,
                'graph_status': c.graph_status,
                'status': c.status,
                'assets': assets,
                'stable_key': f'function_graph_{c.id}',  # 稳定标识用于匹配
            })
        
        with open('reports/graph_export_for_migration.json', 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f'Exported {len(result)} cards')

asyncio.run(export())
"
```

### 2. 复制图像文件

```bash
# 将 generated/ 和 template/ 目录打包
cd backend
tar czf formula_graph_assets.tar.gz static/formulas/graphs/

# 传输到服务器
rsync -az formula_graph_assets.tar.gz -e "ssh -i loginkey.pem" root@8.163.56.109:/opt/2240ai-v2/backend/
```

### 3. 在生产环境导入

```bash
# 在生产服务器上
ssh root@8.163.56.109
cd /opt/2240ai-v2/backend
tar xzf formula_graph_assets.tar.gz

# 运行导入脚本（需先创建导入脚本）
# 导入脚本必须：
# - 按 stable_key（或 title + card_type）匹配，不使用本地自增 ID
# - 不覆盖 source_type=manual 的资源
# - 先 dry-run
# - 验证线上 URL 可访问
```

### 4. 创建受控导入脚本

建议创建 `scripts/import_formula_graphs_for_migration.py`：

```python
"""
Safe import of formula graph assets from development to production.

Matching strategy: card_type='function_graph' matched by title (stable).
Does NOT overwrite manual uploads.

Usage:
    python scripts/import_formula_graphs_for_migration.py --dry-run
    python scripts/import_formula_graphs_for_migration.py --apply
"""
```

### 5. 验证清单

导入后确认：
- [ ] 35 张卡片均 `graph_status=ready`
- [ ] 每张卡片有且仅有一个 effective asset
- [ ] 图像和缩略图文件可访问
- [ ] alt_text 和 description 已迁移
- [ ] 小程序列表使用缩略图
- [ ] 小程序详情使用原图
- [ ] 已有 manual asset 未被覆盖

## 建议的迁移流程

1. **预发布**: 先在预发布环境测试导入流程
2. **Docker**: 生产环境运行在 Docker 中，注意文件挂载路径
3. **PostgreSQL**: 迁移到 PostgreSQL 后，预览 TTL 问题自然解决（支持 timezone-aware datetime）
4. **URL 重写**: 生产环境的 `PUBLIC_BASE_URL` 不同，导入后需重新生成或校验 URL

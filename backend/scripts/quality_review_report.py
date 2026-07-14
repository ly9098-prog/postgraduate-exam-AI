#!/usr/bin/env python3
"""
Phase 4: Generate comprehensive quality review report.
"""
import asyncio
import json
import sys
from datetime import datetime

sys.path.insert(0, '.')

from app.models.formula import FormulaCard, FormulaGraphPreview, FormulaGraphAsset, FormulaCategory
from app.core.config import settings
from sqlalchemy import select
from app.core.database import async_session

REPORT_DIR = "reports"

# Classification categories for quality review
AUTO_APPROVABLE_SIMPLE = [58, 70, 76, 77, 78, 79, 80, 82, 91]  # simple_auto single-panel single-expr
MANUAL_REVIEW = [63, 64, 65, 68, 71, 73, 74, 75, 81, 83, 84, 86, 87, 88, 90, 92]  # multi/compare/asymptotes
FAILED = []

async def generate_report():
    async with async_session() as session:
        # Load all function_graph cards
        r = await session.execute(
            select(FormulaCard).where(
                FormulaCard.card_type == "function_graph",
                FormulaCard.deleted_at.is_(None),
            ).order_by(FormulaCard.id)
        )
        cards = list(r.scalars().all())

        # Load all previews
        r2 = await session.execute(select(FormulaGraphPreview))
        previews = {p.formula_card_id: p for p in r2.scalars().all()}

        # Load all assets
        card_ids = [c.id for c in cards]
        r3 = await session.execute(
            select(FormulaGraphAsset).where(
                FormulaGraphAsset.formula_card_id.in_(card_ids)
            )
        )
        assets_map = {}
        for a in r3.scalars().all():
            assets_map.setdefault(a.formula_card_id, []).append(a)

        result = {
            "timestamp": datetime.now().isoformat(),
            "database": str(settings.DATABASE_URL),
            "total_function_graph": len(cards),
            "summary": {
                "auto_approvable": 0,
                "manual_review": 0,
                "failed": 0,
                "existing_asset_ready": 0,
            },
            "cards": [],
        }

        # Generate markdown
        lines = []
        lines.append("# 公式函数图像生成审核报告")
        lines.append(f"生成时间: {datetime.now().isoformat()}")
        lines.append(f"数据库: {settings.DATABASE_URL}")
        lines.append("")
        lines.append(f"## 总览")
        lines.append(f"- 总 function_graph 公式数: {len(cards)}")
        lines.append("")

        sections = {
            "auto_approvable": [],
            "manual_review": [],
            "failed": [],
            "existing_asset_ready": [],
            "not_applicable": [],
        }

        for c in cards:
            card_assets = assets_map.get(c.id, [])
            has_asset = any(a.image_url for a in card_assets)
            preview = previews.get(c.id)

            item = {
                "id": c.id,
                "title": c.title,
                "card_status": c.status,
                "graph_status": c.graph_status,
                "has_asset": has_asset,
                "asset_types": [a.source_type for a in card_assets],
                "preview_token": preview.preview_token if preview else None,
                "preview_url": preview.preview_url if preview else None,
                "thumbnail_url": preview.thumbnail_url if preview else None,
                "quality_errors": preview.quality_errors if preview else [],
                "quality_warnings": preview.quality_warnings if preview else [],
            }

            # Classify
            if c.graph_status == "ready":
                item["review_category"] = "existing_asset_ready"
                sections["existing_asset_ready"].append(item)
                result["summary"]["existing_asset_ready"] += 1
            elif c.id in FAILED:
                item["review_category"] = "failed"
                sections["failed"].append(item)
                result["summary"]["failed"] += 1
            elif c.id in AUTO_APPROVABLE_SIMPLE:
                item["review_category"] = "auto_approvable"
                sections["auto_approvable"].append(item)
                result["summary"]["auto_approvable"] += 1
            else:
                item["review_category"] = "manual_review"
                sections["manual_review"].append(item)
                result["summary"]["manual_review"] += 1

            result["cards"].append(item)

        # Build markdown per section
        for section_name, section_label in [
            ("auto_approvable", "可直接确认 (auto_approvable)"),
            ("manual_review", "需要人工审核 (manual_review)"),
            ("failed", "生成失败 (failed)"),
            ("existing_asset_ready", "已有有效图像 (ready)"),
        ]:
            items = sections.get(section_name, [])
            lines.append(f"## {section_label}")
            lines.append(f"数量: {len(items)}")
            lines.append("")

            if not items:
                lines.append("无")
                lines.append("")
                continue

            for item in items:
                lines.append(f"### ID={item['id']}: {item['title']}")
                lines.append(f"- 卡片状态: {item['card_status']} | 图像状态: {item['graph_status']}")
                lines.append(f"- 图像资源: {'有' if item['has_asset'] else '无'} ({', '.join(item['asset_types']) if item['asset_types'] else '无'})")

                if item.get("preview_url"):
                    lines.append(f"- 预览: {item['preview_url']}")
                    lines.append(f"- 缩略图: {item['thumbnail_url']}")

                errors = item.get("quality_errors", [])
                warnings = item.get("quality_warnings", [])

                if isinstance(errors, str):
                    errors = json.loads(errors)
                if isinstance(warnings, str):
                    warnings = json.loads(warnings)

                if errors:
                    lines.append(f"- 质量错误: {', '.join(errors)}")
                if warnings:
                    lines.append(f"- 质量警告: {', '.join(warnings)}")

                if section_name == "auto_approvable":
                    lines.append(f"- 推荐操作: 可直接确认发布")
                elif section_name == "manual_review":
                    lines.append(f"- 推荐操作: 人工审核后确认")
                    reasons = []
                    if item['id'] in [63, 64, 65, 73, 74, 75, 86, 87, 88, 90, 92]:
                        reasons.append("多面板/多函数比较")
                    if item['id'] in [81]:
                        reasons.append("含参数")
                    if item['id'] in [83, 84]:
                        reasons.append("示意图/变换演示")
                    if reasons:
                        lines.append(f"- 原因: {'; '.join(reasons)}")
                elif section_name == "failed":
                    lines.append(f"- 失败原因: 见报告")

                lines.append("")

        # Save reports
        json_path = f"{REPORT_DIR}/formula_graph_quality_review.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        md_path = f"{REPORT_DIR}/formula_graph_quality_review.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        print(f"Report saved to {json_path}")
        print(f"Report saved to {md_path}")
        print()
        print("=== Summary ===")
        print(f"auto_approvable: {result['summary']['auto_approvable']}")
        print(f"manual_review: {result['summary']['manual_review']}")
        print(f"failed: {result['summary']['failed']}")
        print(f"existing_asset_ready: {result['summary']['existing_asset_ready']}")


if __name__ == "__main__":
    import os
    os.makedirs(REPORT_DIR, exist_ok=True)
    asyncio.run(generate_report())

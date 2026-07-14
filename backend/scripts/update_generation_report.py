#!/usr/bin/env python3
"""
Update generation report with current state from database.
"""
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, ".")

from app.core.config import settings
from app.models.formula import FormulaCard, FormulaGraphPreview
from app.core.database import async_session
from sqlalchemy import select

REPORT_DIR = "reports"


async def main():
    async with async_session() as session:
        cards_r = await session.execute(
            select(FormulaCard).where(
                FormulaCard.card_type == "function_graph",
                FormulaCard.deleted_at.is_(None),
            ).order_by(FormulaCard.id)
        )
        cards = list(cards_r.scalars().all())

        previews_r = await session.execute(select(FormulaGraphPreview))
        previews = {p.formula_card_id: p for p in previews_r.scalars().all()}

        report_cards = []
        for c in cards:
            p = previews.get(c.id)
            if p:
                errors = p.quality_errors or []
                warnings = p.quality_warnings or []
                if isinstance(errors, str):
                    errors = json.loads(errors)
                if isinstance(warnings, str):
                    warnings = json.loads(warnings)

                item = {
                    "id": c.id,
                    "title": c.title,
                    "status": "success",
                    "preview_token": p.preview_token,
                    "checksum": p.checksum,
                    "preview_url": p.preview_url,
                    "thumbnail_url": p.thumbnail_url,
                    "errors": errors,
                    "warnings": warnings,
                    "quality_passed": len(errors) == 0,
                    "expires_at": p.expires_at.isoformat() if p.expires_at else None,
                }
            elif c.graph_status == "ready":
                item = {
                    "id": c.id,
                    "title": c.title,
                    "status": "existing_asset",
                    "graph_status": "ready",
                }
            else:
                item = {
                    "id": c.id,
                    "title": c.title,
                    "status": "pending",
                    "graph_status": c.graph_status,
                    "graph_last_error": c.graph_last_error,
                }
            report_cards.append(item)

        report = {
            "database_url": str(settings.DATABASE_URL),
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": len(cards),
                "success": sum(1 for c in report_cards if c["status"] == "success"),
                "existing_asset": sum(1 for c in report_cards if c["status"] == "existing_asset"),
                "pending": sum(1 for c in report_cards if c["status"] == "pending"),
            },
            "cards": report_cards,
        }

        json_path = os.path.join(REPORT_DIR, "formula_graph_generation_report.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        # Generate markdown
        md = [
            "# 公式函数图像生成报告",
            f"时间: {datetime.now().isoformat()}",
            f"数据库: {report['database_url']}",
            "",
            "## 摘要",
            f"- 总计: {report['summary']['total']}",
            f"- 预览成功: {report['summary']['success']}",
            f"- 已有图像: {report['summary']['existing_asset']}",
            f"- 待处理: {report['summary']['pending']}",
            "",
            "## 成功生成预览",
        ]
        md.append("| ID | 标题 | 错误 | 警告 | 状态 |")
        md.append("|-----|------|------|------|------|")
        for c in report_cards:
            if c["status"] == "success":
                errs = "; ".join(c.get("errors", [])) or "-"
                warns = "; ".join(c.get("warnings", [])) or "-"
                md.append(f"| {c['id']} | {c['title'][:40]} | {errs} | {warns} | 通过 |")

        md.append("")
        md.append("## 已有图像（template/uploaded）")
        for c in report_cards:
            if c["status"] == "existing_asset":
                md.append(f"- ID={c['id']}: {c['title'][:60]}")

        md.append("")
        md.append("## 待处理")
        for c in report_cards:
            if c["status"] == "pending":
                md.append(f"- ID={c['id']}: {c['title'][:60]} ({c.get('graph_last_error', '')})")

        md_path = os.path.join(REPORT_DIR, "formula_graph_generation_report.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md))

        print(f"Updated {json_path}")
        print(f"Updated {md_path}")
        print(f"Summary: {report['summary']}")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Phase 1: Comprehensive formula graph inventory.

Scans all function_graph cards, analyzes their content, existing assets,
and categorizes them for processing.
"""
import asyncio
import json
import sys
from datetime import datetime

sys.path.insert(0, '.')

from app.models.formula import FormulaCard, FormulaGraphAsset, FormulaCategory
from app.core.config import settings
from sqlalchemy import select
from app.core.database import async_session

REPORT_DIR = "reports"

CATEGORY_MAP = {
    # A - simple_auto (single explicit function)
    "常数函数": "simple_auto",
    "一次函数": "simple_auto",
    "二次函数": "simple_auto",
    "绝对值": "simple_auto",

    # B - comparison_auto (multiple functions in same coordinate)
    "对比": "comparison_auto",
    "对比图": "comparison_auto",

    # C - multi_panel_auto (multiple subplots)
    "间断点": "multi_panel_auto",
    "变换": "multi_panel_auto",
    "关系图": "multi_panel_auto",
    "辅助函数": "multi_panel_auto",

    # D - preset_diagram
    # E - manual_only
    # F - insufficient_data
    # G - wrong_classification
}

def classify_card(card, assets, cat_name):
    """Classify a card into a category for graph generation."""
    title = (card.title or "").lower()
    has_image = any(a.image_url for a in assets)
    has_spec = card.graph_spec is not None

    # Cards with valid assets (template/uploaded) - check if they need upgrade
    if has_image:
        return "existing_asset", "已有图像，检查是否需升级"

    # Classify based on content analysis
    if "常数" in title and "y=c" in title:
        return "simple_auto", "简单常数函数"

    if "一次" in title or ("y=kx" in title and "b" in title):
        return "simple_auto", "一次函数，参数示意"

    if "二次" in title or ("y=ax" in title and "^2" in title):
        return "simple_auto", "二次函数，参数示意"

    if "y=|x|" in title:
        return "simple_auto", "绝对值函数"

    if "y=1/x" in title:
        return "simple_auto", "反比例函数"

    if "幂函数" in title:
        if "正整数" in title or "负整数" in title:
            return "multi_panel_auto", "多面板：不同幂次对比"
        if "有理" in title:
            return "multi_panel_auto", "多面板：有理指数"
        if "对比" in title:
            return "multi_panel_auto", "多面板：α值对比"
        return "multi_panel_auto", "幂函数多对比"

    if "指数函数" in title:
        if "底数对比" in title or "a^x" in title:
            return "comparison_auto", "多底数指数函数对比"
        return "simple_auto", "指数函数"

    if "对数函数" in title:
        if "底数对比" in title or "log_a" in title:
            return "comparison_auto", "多底数对数函数对比"
        if "反函数" in title:
            return "comparison_auto", "指数与对数反函数"
        return "simple_auto", "对数函数"

    if "y=sin" in title:
        return "simple_auto", "正弦函数"
    if "y=cos" in title:
        return "simple_auto", "余弦函数"
    if "正弦与余弦" in title:
        return "comparison_auto", "正弦余弦对比"
    if "y=tan" in title:
        return "simple_auto", "正切函数"
    if "y=cot" in title:
        return "simple_auto", "余切函数"
    if "正切与余切" in title:
        return "comparison_auto", "正切余切对比"
    if "sec" in title or "csc" in title:
        return "comparison_auto", "正割余割对比"

    if "arcsin" in title:
        return "simple_auto", "反正弦"
    if "arccos" in title:
        return "simple_auto", "反余弦"
    if "arctan" in title:
        return "simple_auto", "反正切"
    if "arccot" in title:
        return "simple_auto", "反余切"

    if "y=x+1/x" in title:
        return "simple_auto", "对勾函数"
    if "xe^{-x}" in title:
        return "comparison_auto", "xe^{-x} 与 x^n e^{-x} 对比"
    if "ln x / x" in title or "ln x/x" in title:
        return "simple_auto", "ln(x)/x 函数"
    if "平移" in title:
        return "multi_panel_auto", "平移变换示意图"
    if "综合变换" in title:
        return "multi_panel_auto", "综合变换示意图"
    if "绝对值变换" in title:
        return "multi_panel_auto", "绝对值变换对比"
    if "原函数与导函数" in title:
        return "multi_panel_auto", "原函数与导函数关系"
    if "有理函数" in title:
        return "comparison_auto", "常见有理函数"
    if "增长速度" in title:
        return "comparison_auto", "增长速度对比"
    if "分段" in title:
        return "multi_panel_auto", "分段函数"
    if "间断点" in title:
        return "multi_panel_auto", "四类间断点"
    if "y=x^x" in title:
        return "simple_auto", "幂指函数 y=x^x"
    if "辅助函数" in title:
        return "multi_panel_auto", "辅助函数多面板"

    return "insufficient_data", "无法自动分类"


async def analyze():
    async with async_session() as session:
        # Categories lookup
        r = await session.execute(select(FormulaCategory))
        cats = {c.id: c.name for c in r.scalars().all()}

        # All function_graph cards
        r = await session.execute(
            select(FormulaCard).where(
                FormulaCard.card_type == "function_graph",
                FormulaCard.deleted_at.is_(None),
            ).order_by(FormulaCard.id)
        )
        cards = list(r.scalars().all())

        # Load all assets
        card_ids = [c.id for c in cards]
        assets_r = await session.execute(
            select(FormulaGraphAsset).where(
                FormulaGraphAsset.formula_card_id.in_(card_ids)
            )
        )
        assets_map = {}
        for a in assets_r.scalars().all():
            assets_map.setdefault(a.formula_card_id, []).append(a)

        # Analyze each card
        inventory = []

        # Category counters
        counts = {
            "simple_auto": 0,
            "comparison_auto": 0,
            "multi_panel_auto": 0,
            "preset_diagram": 0,
            "manual_only": 0,
            "insufficient_data": 0,
            "wrong_classification": 0,
            "existing_asset": 0,
        }
        asset_type_counts = {"uploaded": 0, "generated": 0, "template": 0}

        for c in cards:
            cat_name = cats.get(c.category_id, "unknown")
            assets = assets_map.get(c.id, [])
            classification, reason = classify_card(c, assets, cat_name)

            counts[classification] = counts.get(classification, 0) + 1

            for a in assets:
                t = a.source_type
                if t in asset_type_counts:
                    asset_type_counts[t] += 1

            inventory.append({
                "id": c.id,
                "title": c.title,
                "category": cat_name,
                "card_status": c.status,
                "graph_status": c.graph_status,
                "classification": classification,
                "classification_reason": reason,
                "has_graph_spec": c.graph_spec is not None,
                "has_draft_spec": c.draft_graph_spec is not None,
                "graph_last_error": c.graph_last_error,
                "assets": [
                    {
                        "id": a.id,
                        "source_type": a.source_type,
                        "has_image": a.image_url is not None,
                        "template_type": a.template_type,
                        "image_url": a.image_url,
                        "thumbnail_url": a.thumbnail_url,
                        "alt_text": a.alt_text,
                    }
                    for a in assets
                ],
                "asset_count": len(assets),
            })

        print(f"Total function_graph cards: {len(cards)}")
        print()
        print("=== Classification Summary ===")
        for k, v in sorted(counts.items()):
            print(f"  {k}: {v}")
        print()
        print(f"Asset types: {json.dumps(asset_type_counts, ensure_ascii=False)}")
        print()

        # Print detailed inventory
        print("=== Detailed Inventory ===")
        for item in inventory:
            print(f"\nID={item['id']} | {item['title'][:60]}")
            print(f"  分类: {item['classification']} | {item['classification_reason']}")
            print(f"  卡片: status={item['card_status']} | graph_status={item['graph_status']}")
            print(f"  Spec: graph_spec={item['has_graph_spec']} | draft={item['has_draft_spec']}")
            if item['assets']:
                for a in item['assets']:
                    print(f"  Asset: type={a['source_type']} | img={'yes' if a['has_image'] else 'no'} | template={a['template_type']}")
            else:
                print(f"  Assets: none")
            if item['graph_last_error']:
                print(f"  Last error: {item['graph_last_error'][:100]}")

        # Save inventory report
        report = {
            "database_url": str(settings.DATABASE_URL),
            "generated_at": datetime.now().isoformat(),
            "total_function_graph": len(cards),
            "classification_summary": counts,
            "asset_type_counts": asset_type_counts,
            "cards": inventory,
        }

        with open(f"{REPORT_DIR}/formula_graph_inventory.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nInventory saved to {REPORT_DIR}/formula_graph_inventory.json")

        return report


if __name__ == "__main__":
    import os
    os.makedirs(REPORT_DIR, exist_ok=True)
    asyncio.run(analyze())

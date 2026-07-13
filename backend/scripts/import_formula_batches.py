"""
import_formula_batches — Import batch JSON files into formula library DB.

Usage:
    cd backend
    python scripts/import_formula_batches.py

Idempotent: skips cards already imported (by source_ref).
"""
import asyncio
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.core.database import init_db, async_session
from app.core.time_utils import utcnow
from app.models.formula import FormulaCard, FormulaCardTag, FormulaCardVersion, FormulaCategory

BATCH_FILES = [
    "/home/lmh/projects/postgraduate-ai/prompts/tasks/math_chart/batches/batch_01_function_graphs_v1.2.json",
    "/home/lmh/projects/postgraduate-ai/prompts/tasks/math_chart/batches/batch_02_limits_continuity_reviewed.json",
    "/home/lmh/projects/postgraduate-ai/prompts/tasks/math_chart/batches/batch_03_derivatives_reviewed.json",
    "/home/lmh/projects/postgraduate-ai/prompts/tasks/math_chart/batches/batch_04_taylor_integrals_reviewed.json",
]


def make_code(name: str) -> str:
    """Derive a category code from a Chinese/English name."""
    s = name.strip()
    s = s.replace(" ", "_").replace("-", "_")
    s = re.sub(r"[^a-zA-Z0-9_一-鿿]", "", s)
    return s


def compute_content_hash(obj) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def serialize(obj):
    """JSON-serialize an object. Returns string, None for empty."""
    if obj is None:
        return None
    if isinstance(obj, list) and len(obj) == 0:
        return None
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False)


def extract_function_properties(card: dict) -> dict:
    """Extract graph-related fields into function_properties dict."""
    fp = {}

    # Core function graph fields
    for field in [
        "function_expression", "graph_template_type", "graph_render_mode",
        "graph_parameters", "viewport_suggestion", "display_options",
        "annotations", "curves", "multi_panel",
    ]:
        if field in card:
            fp[field] = card[field]

    # Property fields
    for field in [
        "domain", "range", "parity", "period",
        "monotonic_intervals", "extrema", "zeros",
        "asymptotes", "concavity_intervals", "inflection_points",
        "derivative_summary", "one_line_feature", "transformations",
    ]:
        if field in card:
            fp[field] = card[field]

    # Confidence and risk flags from batch metadata
    if "confidence" in card:
        fp["confidence"] = card["confidence"]
    if "risk_flags" in card:
        fp["risk_flags"] = card["risk_flags"]

    return fp if fp else None


def build_card_data(batch_card: dict) -> dict:
    """Map a batch JSON card to FormulaCard fields."""
    card_type = batch_card.get("card_type", "pure_formula")

    # Search text from keywords
    keywords = batch_card.get("keywords", [])
    search_text = " ".join(keywords) if keywords else None

    # formula_blocks — only for pure_formula cards
    formula_blocks = batch_card.get("formula_blocks", [])

    # For function_graph cards without formula_blocks, provide a minimal one
    if card_type == "function_graph" and not formula_blocks:
        formula_blocks = [
            {
                "label": "函数表达式",
                "latex": batch_card.get("function_expression", ""),
                "note": batch_card.get("summary", ""),
            }
        ]

    # Common conclusions → append to secondary_conclusions
    common_conc = batch_card.get("common_conclusions", [])
    secondary = batch_card.get("secondary_conclusions", [])
    if common_conc:
        secondary = (secondary or []) + common_conc

    # Example: serialize arrays, remove review-only fields
    examples_raw = batch_card.get("examples", []) or []
    examples = []
    for ex in examples_raw:
        cleaned = {
            "question": ex.get("question", ""),
            "test_point": ex.get("test_point", ""),
            "short_solution": ex.get("short_solution", ""),
            "answer": ex.get("answer", ""),
            "error_tip": ex.get("error_tip", ""),
            "difficulty": ex.get("difficulty", "中等"),
        }
        # Strip exam-year references
        examples.append(cleaned)

    return {
        "title": batch_card["title"],
        "aliases": batch_card.get("aliases"),
        "search_text": search_text,
        "card_type": card_type,
        "summary": batch_card.get("summary"),
        "formula_blocks": formula_blocks,
        "conditions": serialize(batch_card.get("conditions")),
        "symbol_notes": serialize(batch_card.get("symbol_notes")),
        "secondary_conclusions": serialize(secondary) if secondary else None,
        "error_tips": serialize(batch_card.get("error_tips")),
        "examples": examples if examples else None,
        "function_properties": extract_function_properties(batch_card),
        "status": "draft",
        "source_type": "manual",
        "source_title": batch_card.get("title"),
        "source_ref": batch_card.get("id"),  # e.g. "H-001"
        "content_hash": compute_content_hash(formula_blocks),
    }


async def ensure_category_tree(db, batch_card: dict) -> int:
    """Create or locate the leaf category (group) for a batch card. Returns category_id."""
    subject = batch_card.get("subject", "高数")
    chapter = batch_card.get("chapter", "")
    category = batch_card.get("category", "")

    # Map subject
    if subject == "高数":
        subj_code, subj_name = "math2_high_math", "高等数学"
    elif subject == "线代":
        subj_code, subj_name = "math2_linear_algebra", "线性代数"
    else:
        subj_code, subj_name = subject, subject

    # Create/get subject
    subj = await find_or_create(db, None, subj_code, subj_name, "subject")
    # Create/get chapter
    chap_code = f"{subj_code}__{make_code(chapter)}" if chapter else subj_code
    chap_name = chapter or subj_name
    chap = await find_or_create(db, subj.id, chap_code, chap_name, "chapter")
    # Create/get group
    if category:
        grp_code = f"{chap_code}__{make_code(category)}"
        grp_name = category
    else:
        grp_code = chap_code
        grp_name = chap_name
    grp = await find_or_create(db, chap.id, grp_code, grp_name, "group")
    return grp.id


async def find_or_create(db, parent_id, code, name, node_type):
    """Find an existing category or create one."""
    result = await db.execute(
        select(FormulaCategory).where(
            FormulaCategory.parent_id == parent_id,
            FormulaCategory.code == code,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    cat = FormulaCategory(
        parent_id=parent_id,
        exam_scope="math2",
        node_type=node_type,
        code=code,
        name=name,
        is_active=True,
    )
    db.add(cat)
    await db.flush()
    return cat


def build_snapshot(card: FormulaCard) -> dict:
    return {
        "id": card.id,
        "exam_scope": card.exam_scope,
        "category_id": card.category_id,
        "title": card.title,
        "aliases": card.aliases,
        "search_text": card.search_text,
        "card_type": card.card_type,
        "summary": card.summary,
        "formula_blocks": card.formula_blocks,
        "conditions": card.conditions,
        "symbol_notes": card.symbol_notes,
        "secondary_conclusions": card.secondary_conclusions,
        "error_tips": card.error_tips,
        "examples": card.examples,
        "function_properties": card.function_properties,
        "status": card.status,
        "version": card.version,
    }


async def main():
    print("=" * 60)
    print("Import Formula Batches")
    print("=" * 60)

    # Load all batch files
    all_cards = []
    for bf in BATCH_FILES:
        if not os.path.exists(bf):
            print(f"SKIP: {bf} not found")
            continue
        with open(bf, "r", encoding="utf-8") as f:
            data = json.load(f)
        batch_name = data.get("batch", os.path.basename(bf))
        cards = data.get("cards", [])
        print(f"Loaded {batch_name}: {len(cards)} cards")
        for c in cards:
            c["_batch"] = batch_name
        all_cards.extend(cards)

    print(f"Total cards to import: {len(all_cards)}")

    await init_db()
    async with async_session() as db:
        stats = {"categories_created": 0, "cards_created": 0, "cards_skipped": 0}

        for batch_card in all_cards:
            source_ref = batch_card.get("id", "")
            title = batch_card.get("title", "")
            batch_name = batch_card.get("_batch", "")

            # Skip if already imported (by source_ref)
            existing = await db.execute(
                select(FormulaCard).where(
                    FormulaCard.source_ref == source_ref,
                    FormulaCard.deleted_at.is_(None),
                )
            )
            if existing.scalar_one_or_none():
                stats["cards_skipped"] += 1
                print(f"  SKIP [{source_ref}] {title} (already exists)")
                continue

            # Ensure category tree
            category_id = await ensure_category_tree(db, batch_card)

            # Build card data
            data = build_card_data(batch_card)
            now = utcnow()

            card = FormulaCard(
                exam_scope="math2",
                category_id=category_id,
                title=data["title"],
                aliases=data["aliases"],
                search_text=data["search_text"],
                card_type=data["card_type"],
                summary=data["summary"],
                formula_blocks=data["formula_blocks"],
                conditions=data["conditions"],
                symbol_notes=data["symbol_notes"],
                secondary_conclusions=data["secondary_conclusions"],
                error_tips=data["error_tips"],
                examples=data["examples"],
                function_properties=data["function_properties"],
                status=data["status"],
                source_type=data["source_type"],
                source_title=data["source_title"],
                source_ref=data["source_ref"],
                content_hash=data["content_hash"],
                version=1,
                created_at=now,
                updated_at=now,
            )
            db.add(card)
            await db.flush()

            # Version snapshot
            snapshot = build_snapshot(card)
            db.add(
                FormulaCardVersion(
                    formula_card_id=card.id,
                    version=1,
                    snapshot=snapshot,
                    action="create",
                )
            )

            stats["cards_created"] += 1
            print(f"  OK   [{source_ref}] {title} → category_id={category_id}")

        await db.commit()

    print(f"\n{'=' * 60}")
    print("Import complete!")
    print(f"  Cards created: {stats['cards_created']}")
    print(f"  Cards skipped: {stats['cards_skipped']}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())

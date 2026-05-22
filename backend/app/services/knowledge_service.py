from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import Tag


async def list_tags(db: AsyncSession, subject: str | None = None) -> list[Tag]:
    conditions = []
    if subject:
        conditions.append(Tag.subject == subject)
    q = select(Tag).order_by(Tag.subject, Tag.sort_order, Tag.id)
    if conditions:
        q = q.where(*conditions)
    result = await db.execute(q)
    return list(result.scalars().all())


async def create_tag(db: AsyncSession, name: str, subject: str, parent_id: int | None = None) -> Tag:
    tag = Tag(name=name, subject=subject, parent_id=parent_id)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag


async def delete_tag(db: AsyncSession, tag_id: int) -> bool:
    result = await db.execute(select(Tag).where(Tag.id == tag_id))
    tag = result.scalar_one_or_none()
    if not tag:
        return False
    await db.delete(tag)
    await db.commit()
    return True


def build_tree(tags: list[Tag]) -> dict[str, list[dict]]:
    """将 tag 列表按 subject 分组并构建树形"""
    groups: dict[str, list[Tag]] = {}
    for t in tags:
        groups.setdefault(t.subject, []).append(t)

    result = {}
    for subject, subject_tags in groups.items():
        children = []
        root_nodes = [t for t in subject_tags if t.parent_id is None]
        for root in root_nodes:
            node = _node_to_dict(root, subject_tags)
            children.append(node)
        result[subject] = children
    return result


def _node_to_dict(tag: Tag, all_tags: list[Tag]) -> dict:
    children = [t for t in all_tags if t.parent_id == tag.id]
    return {
        "id": tag.id,
        "name": tag.name,
        "children": [_node_to_dict(c, all_tags) for c in sorted(children, key=lambda x: x.sort_order)],
    }

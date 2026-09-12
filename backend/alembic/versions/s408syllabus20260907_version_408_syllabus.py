"""version 408 syllabus and freeze question-version KP semantics

Revision ID: s408syllabus20260907
Revises: s408error20260907
Create Date: 2026-09-07
"""

import sqlalchemy as sa

from alembic import op

revision = "s408syllabus20260907"
down_revision = "s408error20260907"
branch_labels = None
depends_on = None


def _seed_permission(bind) -> None:
    inspector = sa.inspect(bind)
    if "permissions" not in inspector.get_table_names():
        return
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("resource", sa.String()),
        sa.column("action", sa.String()),
        sa.column("category", sa.String()),
        sa.column("description", sa.String()),
    )
    roles = sa.table("roles", sa.column("id", sa.Integer()), sa.column("name", sa.String()))
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Integer()),
        sa.column("permission_id", sa.Integer()),
    )
    permission_id = bind.execute(
        sa.select(permissions.c.id).where(permissions.c.name == "knowledge:write")
    ).scalar_one_or_none()
    if permission_id is None:
        bind.execute(
            permissions.insert().values(
                name="knowledge:write",
                resource="knowledge",
                action="write",
                category="knowledge",
                description="管理考纲版本与知识点范围",
            )
        )
        permission_id = bind.execute(
            sa.select(permissions.c.id).where(permissions.c.name == "knowledge:write")
        ).scalar_one()
    for role_name in ("super_admin", "admin"):
        role_id = bind.execute(sa.select(roles.c.id).where(roles.c.name == role_name)).scalar_one_or_none()
        if role_id is None:
            continue
        exists = bind.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == permission_id,
            )
        ).scalar_one_or_none()
        if exists is None:
            bind.execute(role_permissions.insert().values(role_id=role_id, permission_id=permission_id))


def _seed_baseline(bind) -> None:
    subjects = sa.table(
        "subjects",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("sort_order", sa.Integer()),
    )
    versions = sa.table(
        "syllabus_versions",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("root_subject_id", sa.Integer()),
        sa.column("effective_year", sa.SmallInteger()),
        sa.column("status", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("activated_at", sa.DateTime()),
    )
    kps = sa.table(
        "knowledge_points",
        sa.column("id", sa.Integer()),
        sa.column("subject_id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("normalized_name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("difficulty_level", sa.SmallInteger()),
        sa.column("is_active", sa.Boolean()),
    )
    members = sa.table(
        "syllabus_knowledge_points",
        sa.column("id", sa.Integer()),
        sa.column("syllabus_version_id", sa.Integer()),
        sa.column("knowledge_point_id", sa.Integer()),
        sa.column("subject_id", sa.Integer()),
        sa.column("name_snapshot", sa.String()),
        sa.column("normalized_name_snapshot", sa.String()),
        sa.column("description_snapshot", sa.Text()),
        sa.column("difficulty_level_snapshot", sa.SmallInteger()),
        sa.column("sort_order", sa.Integer()),
    )

    root_id = bind.execute(
        sa.select(subjects.c.id).where(subjects.c.code == "exam408")
    ).scalar_one_or_none()
    if root_id is None:
        return
    version_id = bind.execute(
        sa.select(versions.c.id).where(versions.c.code == "exam408-2026-baseline")
    ).scalar_one_or_none()
    if version_id is None:
        bind.execute(
            versions.insert().values(
                code="exam408-2026-baseline",
                name="408 当前知识体系基线",
                root_subject_id=root_id,
                effective_year=2026,
                status="active",
                description="408-SYLLABUS 上线时从现有 active 知识点冻结生成的迁移基线。",
                activated_at=sa.func.now(),
            )
        )
        version_id = bind.execute(
            sa.select(versions.c.id).where(versions.c.code == "exam408-2026-baseline")
        ).scalar_one()

    core_codes = (
        "data_structure",
        "computer_organization",
        "operating_system",
        "computer_network",
    )
    core_rows = bind.execute(
        sa.select(subjects.c.id, subjects.c.sort_order)
        .where(subjects.c.code.in_(core_codes))
    ).all()
    core_ids = [row.id for row in core_rows]
    if not core_ids:
        return
    existing_kp_ids = set(bind.execute(
        sa.select(members.c.knowledge_point_id).where(members.c.syllabus_version_id == version_id)
    ).scalars().all())
    rows = bind.execute(
        sa.select(
            kps.c.id,
            kps.c.subject_id,
            kps.c.name,
            kps.c.normalized_name,
            kps.c.description,
            kps.c.difficulty_level,
        )
        .join(subjects, subjects.c.id == kps.c.subject_id)
        .where(kps.c.subject_id.in_(core_ids), kps.c.is_active == sa.true())
        .order_by(subjects.c.sort_order.asc(), kps.c.name.asc(), kps.c.id.asc())
    ).all()
    order_by_subject: dict[int, int] = {}
    for row in rows:
        if row.id in existing_kp_ids:
            continue
        order_by_subject[row.subject_id] = order_by_subject.get(row.subject_id, 0) + 10
        bind.execute(
            members.insert().values(
                syllabus_version_id=version_id,
                knowledge_point_id=row.id,
                subject_id=row.subject_id,
                name_snapshot=row.name,
                normalized_name_snapshot=row.normalized_name,
                description_snapshot=row.description,
                difficulty_level_snapshot=row.difficulty_level or 3,
                sort_order=order_by_subject[row.subject_id],
            )
        )


def _backfill_qvkp_membership(bind) -> None:
    qvkp = sa.table(
        "question_version_knowledge_points",
        sa.column("id", sa.Integer()),
        sa.column("knowledge_point_id", sa.Integer()),
        sa.column("syllabus_knowledge_point_id", sa.Integer()),
    )
    versions = sa.table(
        "syllabus_versions",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
    )
    members = sa.table(
        "syllabus_knowledge_points",
        sa.column("id", sa.Integer()),
        sa.column("syllabus_version_id", sa.Integer()),
        sa.column("knowledge_point_id", sa.Integer()),
    )
    version_id = bind.execute(
        sa.select(versions.c.id).where(versions.c.code == "exam408-2026-baseline")
    ).scalar_one_or_none()
    if version_id is None:
        return
    member_rows = bind.execute(
        sa.select(members.c.knowledge_point_id, members.c.id).where(
            members.c.syllabus_version_id == version_id
        )
    ).all()
    for kp_id, member_id in member_rows:
        bind.execute(
            qvkp.update()
            .where(
                qvkp.c.knowledge_point_id == kp_id,
                qvkp.c.syllabus_knowledge_point_id.is_(None),
            )
            .values(syllabus_knowledge_point_id=member_id)
        )


def upgrade() -> None:
    op.create_table(
        "syllabus_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("root_subject_id", sa.Integer(), sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("effective_year", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_syllabus_versions_code"),
        sa.CheckConstraint("status IN ('draft','active','archived')", name="ck_syllabus_versions_status"),
        sa.CheckConstraint("effective_year >= 2000 AND effective_year <= 2200", name="ck_syllabus_versions_year"),
    )
    op.create_index("ix_syllabus_versions_code", "syllabus_versions", ["code"])
    op.create_index("ix_syllabus_versions_root_subject_id", "syllabus_versions", ["root_subject_id"])
    op.create_index("ix_syllabus_versions_effective_year", "syllabus_versions", ["effective_year"])
    op.create_index("ix_syllabus_versions_status", "syllabus_versions", ["status"])
    op.create_index(
        "uq_syllabus_versions_one_active",
        "syllabus_versions",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "syllabus_knowledge_points",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("syllabus_version_id", sa.Integer(), sa.ForeignKey("syllabus_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("knowledge_point_id", sa.Integer(), sa.ForeignKey("knowledge_points.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name_snapshot", sa.String(length=128), nullable=False),
        sa.Column("normalized_name_snapshot", sa.String(length=128), nullable=False),
        sa.Column("description_snapshot", sa.Text(), nullable=True),
        sa.Column("difficulty_level_snapshot", sa.SmallInteger(), nullable=False, server_default="3"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("syllabus_version_id", "knowledge_point_id", name="uq_syllabus_version_kp"),
        sa.CheckConstraint("difficulty_level_snapshot >= 1 AND difficulty_level_snapshot <= 5", name="ck_syllabus_kp_difficulty"),
    )
    op.create_index("ix_syllabus_knowledge_points_syllabus_version_id", "syllabus_knowledge_points", ["syllabus_version_id"])
    op.create_index("ix_syllabus_knowledge_points_knowledge_point_id", "syllabus_knowledge_points", ["knowledge_point_id"])
    op.create_index("ix_syllabus_knowledge_points_subject_id", "syllabus_knowledge_points", ["subject_id"])

    op.create_table(
        "syllabus_knowledge_point_mappings",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("from_syllabus_knowledge_point_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), sa.ForeignKey("syllabus_knowledge_points.id", ondelete="CASCADE"), nullable=True),
        sa.Column("to_syllabus_knowledge_point_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), sa.ForeignKey("syllabus_knowledge_points.id", ondelete="CASCADE"), nullable=True),
        sa.Column("relation_type", sa.String(length=16), nullable=False),
        sa.Column("note", sa.String(length=256), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("admin_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("relation_type IN ('unchanged','renamed','added','removed','merged','split','replaced')", name="ck_syllabus_kp_mapping_type"),
        sa.CheckConstraint("from_syllabus_knowledge_point_id IS NOT NULL OR to_syllabus_knowledge_point_id IS NOT NULL", name="ck_syllabus_kp_mapping_endpoint"),
    )
    op.create_index(
        "ix_syllabus_kp_mappings_from_kp_id",
        "syllabus_knowledge_point_mappings",
        ["from_syllabus_knowledge_point_id"],
    )
    op.create_index(
        "ix_syllabus_kp_mappings_to_kp_id",
        "syllabus_knowledge_point_mappings",
        ["to_syllabus_knowledge_point_id"],
    )

    _seed_permission(op.get_bind())
    _seed_baseline(op.get_bind())

    with op.batch_alter_table("question_version_knowledge_points") as batch:
        batch.add_column(sa.Column("syllabus_knowledge_point_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True))
        batch.create_foreign_key(
            "fk_qvkp_syllabus_knowledge_point",
            "syllabus_knowledge_points",
            ["syllabus_knowledge_point_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_qvkp_syllabus_kp_id",
        "question_version_knowledge_points",
        ["syllabus_knowledge_point_id"],
    )
    _backfill_qvkp_membership(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_qvkp_syllabus_kp_id", table_name="question_version_knowledge_points")
    with op.batch_alter_table("question_version_knowledge_points") as batch:
        batch.drop_constraint("fk_qvkp_syllabus_knowledge_point", type_="foreignkey")
        batch.drop_column("syllabus_knowledge_point_id")

    # Do not delete ``knowledge:write`` during downgrade.  The permission may
    # have existed before this migration (or may already be used by another
    # deployment path), and Alembic cannot reliably tell whether this revision
    # created it.  Leaving an unused RBAC permission is safer than deleting
    # pre-existing authorization data.

    op.drop_index("ix_syllabus_kp_mappings_to_kp_id", table_name="syllabus_knowledge_point_mappings")
    op.drop_index("ix_syllabus_kp_mappings_from_kp_id", table_name="syllabus_knowledge_point_mappings")
    op.drop_table("syllabus_knowledge_point_mappings")
    op.drop_table("syllabus_knowledge_points")
    op.drop_index("uq_syllabus_versions_one_active", table_name="syllabus_versions")
    op.drop_table("syllabus_versions")

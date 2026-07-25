from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FormulaCategory(Base):
    __tablename__ = "formula_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("formula_categories.id"), nullable=True, index=True
    )
    exam_scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default="math2", index=True
    )
    node_type: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # subject | chapter | group
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "parent_id", "code", name="uq_formula_categories_parent_code"
        ),
    )


class FormulaTag(Base):
    __tablename__ = "formula_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class FormulaCard(Base):
    __tablename__ = "formula_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exam_scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default="math2", index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("formula_categories.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    search_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    card_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pure_formula"
    )  # auto | pure_formula | function_graph
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    formula_blocks: Mapped[list] = mapped_column(JSON, nullable=False)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    symbol_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    secondary_conclusions: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_tips: Mapped[str | None] = mapped_column(Text, nullable=True)
    examples: Mapped[list | None] = mapped_column(JSON, nullable=True)
    function_properties: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", index=True
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True
    )
    source_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # manual | ai | ocr | import
    source_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    # Graph generation fields
    graph_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    draft_graph_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    graph_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_applicable",
        server_default="not_applicable", index=True,
    )
    graph_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    graph_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    graph_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class FormulaCardTag(Base):
    __tablename__ = "formula_card_tags"
    __table_args__ = (
        UniqueConstraint(
            "formula_card_id", "tag_id", name="uq_formula_card_tags_card_tag"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    formula_card_id: Mapped[int] = mapped_column(
        ForeignKey("formula_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("formula_tags.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class FormulaGraphAsset(Base):
    __tablename__ = "formula_graph_assets"
    __table_args__ = (
        UniqueConstraint(
            "formula_card_id", "source_type",
            name="uq_formula_graph_assets_card_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    formula_card_id: Mapped[int] = mapped_column(
        ForeignKey("formula_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # uploaded | template | generated
    template_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    template_parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    viewport: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_svg_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    renderer_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alt_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class FormulaGraphPreview(Base):
    """Tracks unconfirmed preview images with expiry.

    Each card has at most one active preview at a time.
    """

    __tablename__ = "formula_graph_previews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    formula_card_id: Mapped[int] = mapped_column(
        ForeignKey("formula_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    preview_token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    renderer_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    quality_warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class FormulaGraphSpec(Base):
    """One-to-many graph specs per formula card.

    Each spec has a stable slug for cross-environment identity.
    Multiple specs per card are independent — each has its own
    status, asset, review trail and sort order.
    """

    __tablename__ = "formula_graph_specs"
    __table_args__ = (
        UniqueConstraint(
            "formula_card_id", "slug",
            name="uq_formula_graph_specs_card_slug",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    formula_card_id: Mapped[int] = mapped_column(
        ForeignKey("formula_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    renderer_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("formula_graph_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class FormulaCardVersion(Base):
    __tablename__ = "formula_card_versions"
    __table_args__ = (
        UniqueConstraint(
            "formula_card_id", "version",
            name="uq_formula_card_versions_card_version",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    formula_card_id: Mapped[int] = mapped_column(
        ForeignKey("formula_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    action: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # create | update | review | publish | offline | delete
    edited_by: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True
    )
    edit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class UserFormulaFavorite(Base):
    __tablename__ = "user_formula_favorites"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "formula_card_id",
            name="uq_user_formula_favorites_user_card",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    formula_card_id: Mapped[int] = mapped_column(
        ForeignKey("formula_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class FormulaImportJob(Base):
    __tablename__ = "formula_import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # text | pdf | image | excel | json | markdown
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String(256), nullable=True)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_items: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_of: Mapped[int | None] = mapped_column(
        ForeignKey("formula_import_jobs.id"), nullable=True
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # P0-1 fencing: execution generation prevents stale workers from writing
    execution_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_owner_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_status: Mapped[str | None] = mapped_column(String(16), nullable=True)


class FormulaImportItem(Base):
    __tablename__ = "formula_import_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("formula_import_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_locator: Mapped[str | None] = mapped_column(String(256), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    generated_content: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    card_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    latex_valid: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=None
    )
    latex_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scope_check: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duplicate_check: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("formula_cards.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

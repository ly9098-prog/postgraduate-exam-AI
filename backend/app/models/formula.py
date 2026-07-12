from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    SmallInteger,
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
    )  # pure_formula | function_graph
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
    )  # uploaded | template
    template_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    template_parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    viewport: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_svg_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
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

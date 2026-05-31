from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AppUserAdminBinding(Base):
    __tablename__ = "app_user_admin_bindings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_app_user_admin_bindings_user_id"),
        UniqueConstraint("admin_user_id", name="uq_app_user_admin_bindings_admin_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user = relationship("User")
    admin_user = relationship("AdminUser", foreign_keys=[admin_user_id])
    creator = relationship("AdminUser", foreign_keys=[created_by])

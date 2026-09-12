"""add_review_schedules_and_review_records

Revision ID: e4a51b2293da
Revises: 7a1cf3e9d2b4
Create Date: 2026-05-24 20:14:38.251477

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'e4a51b2293da'
down_revision: Union[str, Sequence[str], None] = '7a1cf3e9d2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('review_schedules',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('subject', sa.String(length=16), nullable=True),
        sa.Column('interval', sa.Integer(), nullable=False),
        sa.Column('ease_factor', sa.Float(), nullable=False),
        sa.Column('repetitions', sa.Integer(), nullable=False),
        sa.Column('next_review_at', sa.DateTime(), nullable=True),
        sa.Column('last_reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_review_schedules_user_id', 'review_schedules', ['user_id'])
    # Composite index for today's review queue
    op.create_index('ix_review_schedules_user_next_review', 'review_schedules', ['user_id', 'next_review_at'])
    op.create_index('ix_review_schedules_user_subject', 'review_schedules', ['user_id', 'subject'])

    op.create_table('review_records',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('schedule_id', sa.Integer(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('interval_before', sa.Integer(), nullable=True),
        sa.Column('interval_after', sa.Integer(), nullable=True),
        sa.Column('ease_factor_before', sa.Float(), nullable=True),
        sa.Column('ease_factor_after', sa.Float(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id']),
        sa.ForeignKeyConstraint(['schedule_id'], ['review_schedules.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_review_records_user_id', 'review_records', ['user_id'])
    op.create_index('ix_review_records_user_reviewed', 'review_records', ['user_id', 'reviewed_at'])


def downgrade() -> None:
    op.drop_index('ix_review_records_user_reviewed', table_name='review_records')
    op.drop_index('ix_review_records_user_id', table_name='review_records')
    op.drop_table('review_records')
    op.drop_index('ix_review_schedules_user_subject', table_name='review_schedules')
    op.drop_index('ix_review_schedules_user_next_review', table_name='review_schedules')
    op.drop_index('ix_review_schedules_user_id', table_name='review_schedules')
    op.drop_table('review_schedules')

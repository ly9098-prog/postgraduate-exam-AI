"""add ocr_jobs table

Revision ID: 0d608fe34f9d
Revises: v10_question_type_check_constraints
Create Date: 2026-07-17 16:38:52.841841

Note: Only creates ocr_jobs table + indexes. Other schema differences
detected by autogenerate (dropped tables, FK constraints, index renames)
are SQLite-specific artifacts and are NOT included in this migration.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = '0d608fe34f9d'
down_revision: Union[str, Sequence[str], None] = 'v10_question_type_check_constraints'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('ocr_jobs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('request_id', sa.String(length=64), nullable=False),
        sa.Column('document_id', sa.String(length=64), nullable=False),
        sa.Column('document_sha256', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('input_artifact_key', sa.String(length=256), nullable=False),
        sa.Column('input_mime_type', sa.String(length=64), nullable=False),
        sa.Column('input_size_bytes', sa.Integer(), nullable=False),
        sa.Column('input_page_count', sa.Integer(), nullable=True),
        sa.Column('output_artifact_key', sa.String(length=256), nullable=True),
        sa.Column('output_sha256', sa.String(length=64), nullable=True),
        sa.Column('lease_owner', sa.String(length=64), nullable=True),
        sa.Column('lease_token_hash', sa.String(length=64), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        sa.Column('last_error_code', sa.String(length=32), nullable=True),
        sa.Column('last_error_message', sa.Text(), nullable=True),
        sa.Column('pipeline_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('required_document_ir_schema', sa.String(length=16), nullable=False),
        sa.Column('worker_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('model_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('complete_idempotency_key', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('request_id', name='uq_ocr_jobs_request_id'),
        sa.UniqueConstraint('complete_idempotency_key', name='uq_ocr_jobs_complete_key'),
    )
    # Indexes for claim_job query performance
    op.create_index('ix_ocr_jobs_claim', 'ocr_jobs', ['status', 'priority', 'next_retry_at', 'created_at'], unique=False)
    op.create_index('ix_ocr_jobs_lease_expires_at', 'ocr_jobs', ['lease_expires_at'], unique=False)
    op.create_index('ix_ocr_jobs_document_sha256', 'ocr_jobs', ['document_sha256'], unique=False)
    op.create_index(op.f('ix_ocr_jobs_document_id'), 'ocr_jobs', ['document_id'], unique=False)
    op.create_index(op.f('ix_ocr_jobs_request_id'), 'ocr_jobs', ['request_id'], unique=False)
    op.create_index(op.f('ix_ocr_jobs_status'), 'ocr_jobs', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ocr_jobs_status'), table_name='ocr_jobs')
    op.drop_index(op.f('ix_ocr_jobs_request_id'), table_name='ocr_jobs')
    op.drop_index(op.f('ix_ocr_jobs_document_id'), table_name='ocr_jobs')
    op.drop_index('ix_ocr_jobs_document_sha256', table_name='ocr_jobs')
    op.drop_index('ix_ocr_jobs_lease_expires_at', table_name='ocr_jobs')
    op.drop_index('ix_ocr_jobs_claim', table_name='ocr_jobs')
    op.drop_table('ocr_jobs')

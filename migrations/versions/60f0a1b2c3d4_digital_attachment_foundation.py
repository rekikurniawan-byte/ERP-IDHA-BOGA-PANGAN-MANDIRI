"""digital attachment foundation

Revision ID: 60f0a1b2c3d4
Revises: 60c0a1b2c3d4
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa


revision = "60f0a1b2c3d4"
down_revision = "60c0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "digital_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("module", sa.String(length=60), nullable=False),
        sa.Column("reference_type", sa.String(length=80), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=False),
        sa.Column("attachment_type", sa.String(length=80), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("delete_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_filename"),
    )
    op.create_index(op.f("ix_digital_attachments_branch_id"), "digital_attachments", ["branch_id"], unique=False)
    op.create_index(op.f("ix_digital_attachments_module"), "digital_attachments", ["module"], unique=False)
    op.create_index(op.f("ix_digital_attachments_reference_type"), "digital_attachments", ["reference_type"], unique=False)
    op.create_index(op.f("ix_digital_attachments_reference_id"), "digital_attachments", ["reference_id"], unique=False)
    op.create_index(op.f("ix_digital_attachments_attachment_type"), "digital_attachments", ["attachment_type"], unique=False)
    op.create_index(op.f("ix_digital_attachments_sha256_hash"), "digital_attachments", ["sha256_hash"], unique=False)
    op.create_index(op.f("ix_digital_attachments_uploaded_by"), "digital_attachments", ["uploaded_by"], unique=False)
    op.create_index(op.f("ix_digital_attachments_is_deleted"), "digital_attachments", ["is_deleted"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_digital_attachments_is_deleted"), table_name="digital_attachments")
    op.drop_index(op.f("ix_digital_attachments_uploaded_by"), table_name="digital_attachments")
    op.drop_index(op.f("ix_digital_attachments_sha256_hash"), table_name="digital_attachments")
    op.drop_index(op.f("ix_digital_attachments_attachment_type"), table_name="digital_attachments")
    op.drop_index(op.f("ix_digital_attachments_reference_id"), table_name="digital_attachments")
    op.drop_index(op.f("ix_digital_attachments_reference_type"), table_name="digital_attachments")
    op.drop_index(op.f("ix_digital_attachments_module"), table_name="digital_attachments")
    op.drop_index(op.f("ix_digital_attachments_branch_id"), table_name="digital_attachments")
    op.drop_table("digital_attachments")
